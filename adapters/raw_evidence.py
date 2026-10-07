"""Direct concurrent capture of unfiltered SAM, OCR, and RMBG evidence."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request
import uuid

from PIL import Image, ImageOps


DEFAULT_SAM_PROMPTS: tuple[Mapping[str, Any], ...] = (
    {"id": "arrow", "text": "arrow", "confidence_threshold": 0.30},
    {"id": "border", "text": "border", "confidence_threshold": 0.30},
    {"id": "content_box", "text": "content box", "confidence_threshold": 0.15},
    {"id": "cube", "text": "cube or cuboid", "confidence_threshold": 0.20},
    {"id": "diagram", "text": "diagram", "confidence_threshold": 0.20},
    {"id": "geometric_shape", "text": "geometric shape", "confidence_threshold": 0.20},
    {"id": "grid", "text": "grid", "confidence_threshold": 0.30},
    {"id": "icon", "text": "icon", "confidence_threshold": 0.30},
    {"id": "picture", "text": "picture", "confidence_threshold": 0.30},
    {"id": "polygon", "text": "polygon", "confidence_threshold": 0.25},
    {"id": "rectangle", "text": "rectangle or panel", "confidence_threshold": 0.20},
)

_CATALOG_SCHEMA = "figfox.shared_evidence_catalog.v1"
_MANIFEST_SCHEMA = "figfox.raw_evidence_manifest.v1"


class _TimedRawSourceError(Exception):
    """Carry measured worker time without exposing the provider's message."""

    def __init__(self, original: Exception, elapsed_ms: float) -> None:
        super().__init__("raw source request failed")
        self.original_type = type(original).__name__
        self.elapsed_ms = elapsed_ms
        self.retryable = (
            isinstance(original, urllib_error.HTTPError)
            and 500 <= int(original.code) < 600
        )


@dataclass(frozen=True)
class RawEvidenceOptions:
    service_base_url: str = "http://127.0.0.1:18080"
    timeout_seconds: float = 600.0
    sam_prompts: tuple[Mapping[str, Any], ...] = DEFAULT_SAM_PROMPTS


@dataclass(frozen=True)
class RawEvidenceResult:
    catalog_path: Path
    manifest_path: Path
    source_status: Mapping[str, str]
    artifacts: tuple[Mapping[str, Any], ...]
    timings_ms: Mapping[str, float]
    image_size: tuple[int, int]


@dataclass(frozen=True)
class RawEvidenceSourceReady:
    """One raw source made available while its siblings may still be running."""

    source: str
    assets: tuple[Mapping[str, Any], ...]
    elapsed_ms: float
    image_size: tuple[int, int]
    catalog_path: Path | None = None


@dataclass(frozen=True)
class RawEvidenceSourceTerminal:
    """A source has a final outcome, independent of sibling completion."""
    source: str
    status: str
    elapsed_ms: float
    error_type: str | None = None


class _HttpJsonTransport:
    def __init__(self, service_base_url: str) -> None:
        self.service_base_url = service_base_url.rstrip("/")

    def post_json(
        self, path: str, payload: Mapping[str, Any], timeout_seconds: float
    ) -> Mapping[str, Any]:
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        http_request = urllib_request.Request(
            self.service_base_url + path,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(http_request, timeout=timeout_seconds) as response:
            response_body = response.read()
        decoded = json.loads(response_body.decode("utf-8"))
        if not isinstance(decoded, Mapping):
            raise ValueError("raw evidence service response must be a JSON object")
        return decoded


class RawEvidenceCollector:
    """Capture three independent raw sources without invoking any planning pipeline."""

    def __init__(self, options: RawEvidenceOptions, *, transport: Any | None = None):
        self.options = options
        self.transport = transport or _HttpJsonTransport(options.service_base_url)

    def collect(
        self,
        original_path: Path,
        output_dir: Path,
        *,
        source_ready: Callable[[RawEvidenceSourceReady], None] | None = None,
        source_terminal: Callable[[RawEvidenceSourceTerminal], None] | None = None,
        sources: tuple[str, ...] = ("sam", "ocr", "rmbg"),
    ) -> RawEvidenceResult:
        if not sources or len(set(sources)) != len(sources) or any(s not in {"sam", "ocr", "rmbg"} for s in sources):
            raise ValueError("sources must contain distinct supported source names")
        _original, original_sha256, canonical_image, canonical_bytes = canonical_original_snapshot(
            original_path
        )
        image_size = canonical_image.size
        canonical_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
        encoded = base64.b64encode(canonical_bytes).decode("ascii")
        output = _new_output_path(output_dir)
        run_prefix = f"figfox-{output.name}-{uuid.uuid4().hex}"
        prompts = [dict(prompt) for prompt in self.options.sam_prompts]
        requests: dict[str, tuple[str, Mapping[str, Any]]] = {
            "sam": (
                "/v1/segment/proposals",
                {
                    "image_base64": encoded,
                    "prompts": prompts,
                    "merge_threshold": 0.0,
                    "return_overlay": False,
                    "return_masks": True,
                    "artifact_prefix": f"{run_prefix}-sam",
                },
            ),
            "ocr": (
                "/v1/ocr/boxes",
                {
                    "image_base64": encoded,
                    "filename": "ORIGINAL.canonical.png",
                    "image_sha256": canonical_sha256,
                    "image_bytes": len(canonical_bytes),
                },
            ),
            "rmbg": (
                "/v1/rmbg/remove-background",
                {
                    "image_base64": encoded,
                    "output_name": "ORIGINAL.nobg.png",
                    "return_image": True,
                    "artifact_prefix": f"{run_prefix}-rmbg",
                },
            ),
        }

        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-staging-", dir=output.parent))
        try:
            _write_bytes(stage / "request_image.png", canonical_bytes)
            responses: dict[str, Mapping[str, Any]] = {}
            localized_assets: dict[str, list[dict[str, Any]]] = {}
            failures: dict[str, str] = {}
            callback_errors: list[BaseException] = []
            timings_ms: dict[str, float] = {}
            with ThreadPoolExecutor(max_workers=len(sources)) as executor:
                futures = {
                    executor.submit(self._request_with_retry, source,
                        *requests[source], stage, canonical_image, image_size): source
                    for source in sources
                }
                for future in as_completed(futures):
                    source = futures[future]
                    error_type = None
                    try:
                        response, elapsed_ms, worker_assets, ready_assets = future.result()
                        responses[source] = response
                        localized_assets[source] = worker_assets
                        timings_ms[source] = elapsed_ms
                        if source_ready is not None:
                            try:
                                source_ready(RawEvidenceSourceReady(
                                    source=source, assets=ready_assets, elapsed_ms=elapsed_ms,
                                    image_size=image_size, catalog_path=_publish_ready_catalog(
                                        stage, output, source, worker_assets, image_size,
                                        original_sha256, canonical_sha256)))
                            except BaseException as callback_error:
                                callback_errors.append(callback_error)
                                error_type = type(callback_error).__name__
                    except Exception as error:
                        elapsed_ms = getattr(error, "elapsed_ms", None)
                        if (isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, (int, float))
                                or not math.isfinite(elapsed_ms) or elapsed_ms < 0):
                            raise RuntimeError("raw source failure did not include measured elapsed time") from error
                        timings_ms[source] = float(elapsed_ms)
                        error_type = getattr(error, "original_type", type(error).__name__)
                        failures[source] = error_type
                    if source_terminal is not None:
                        try:
                            source_terminal(RawEvidenceSourceTerminal(source,
                                "unavailable" if error_type else "ready", timings_ms[source], error_type))
                        except BaseException as callback_error:
                            callback_errors.append(callback_error)

            catalog_assets: list[dict[str, Any]] = []
            source_status: dict[str, str] = {}
            diagnostics: dict[str, Mapping[str, str]] = {}
            for source in sources:
                if source in failures:
                    source_status[source] = "unavailable"
                    diagnostics[source] = {
                        "error_type": failures[source],
                        "message": "raw source request failed",
                    }
                    _remove_source_derivatives(stage, source)
                    continue
                response = responses[source]
                try:
                    if source == "sam":
                        catalog_assets.extend(localized_assets[source])
                    else:
                        catalog_assets.extend(localized_assets[source])
                except Exception as error:
                    source_status[source] = "unavailable"
                    diagnostics[source] = {
                        "error_type": type(error).__name__,
                        "message": "raw source evidence failed integrity validation",
                    }
                    catalog_assets = [
                        item for item in catalog_assets if not _from_source(item, source)
                    ]
                    _remove_source_derivatives(stage, source)
                else:
                    source_status[source] = "ok"

            catalog = {
                "schema": _CATALOG_SCHEMA,
                "original_sha256": original_sha256,
                "canonical_sha256": canonical_sha256,
                "image_size": list(image_size),
                "assets": catalog_assets,
            }
            _write_json(stage / "catalog.json", catalog)
            inventory = _inventory(stage)
            manifest = {
                "schema": _MANIFEST_SCHEMA,
                "source_status": source_status,
                "timings_ms": timings_ms,
                "diagnostics": diagnostics,
                # A manifest cannot include its own final digest; it authenticates every
                # other published regular file, including the consumer catalog.
                "files": inventory,
            }
            _write_json(stage / "manifest.json", manifest)
            os.replace(stage, output)
            _fsync_directory(output.parent)
            if callback_errors:
                raise callback_errors[0]
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        finally:
            canonical_image.close()

        final_artifacts = tuple(dict(item) for item in inventory)
        return RawEvidenceResult(
            catalog_path=output / "catalog.json",
            manifest_path=output / "manifest.json",
            source_status=dict(source_status),
            artifacts=final_artifacts,
            timings_ms=dict(timings_ms),
            image_size=image_size,
        )

    def _request_with_retry(self, source, path, payload, stage, canonical_image, image_size):
        elapsed = 0.0
        for attempt in range(2):
            try:
                response, duration, assets = self._request_one(
                    source, path, payload, stage, canonical_image, image_size)
                elapsed += duration
                try:
                    ready = _source_ready_assets(source, response, assets, image_size)
                except Exception as error:
                    raise _TimedRawSourceError(error, 0.0) from error
                return response, elapsed, assets, ready
            except _TimedRawSourceError as error:
                elapsed += error.elapsed_ms
                error.elapsed_ms = elapsed
                if attempt or not error.retryable:
                    raise
                _remove_source_derivatives(stage, source)
        raise AssertionError("unreachable source retry")

    def _request_one(
        self,
        source: str,
        path: str,
        payload: Mapping[str, Any],
        stage: Path,
        canonical_image: Image.Image,
        image_size: tuple[int, int],
    ) -> tuple[Mapping[str, Any], float, list[dict[str, Any]]]:
        started = time.perf_counter()
        try:
            response = self.transport.post_json(
                path, payload, self.options.timeout_seconds
            )
            if not isinstance(response, Mapping):
                raise ValueError("raw evidence service response must be a mapping")
            # Canonical JSON validation prevents late partial publication.
            _json_bytes(response)
            worker_assets = (
                _persist_sam(stage, response, canonical_image, image_size)
                if source == "sam"
                else _persist_ocr(stage, response, canonical_image, image_size)
                if source == "ocr"
                else [_persist_rmbg(stage, response, image_size)]
            )
            return response, (time.perf_counter() - started) * 1000.0, worker_assets
        except Exception as error:
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            raise _TimedRawSourceError(error, elapsed_ms) from error


def _publish_ready_catalog(
    stage: Path, output: Path, source: str,
    assets: Sequence[Mapping[str, Any]], image_size: tuple[int, int],
    original_sha256: str, canonical_sha256: str,
) -> Path:
    """Publish stable source files before the other workers finish.

    The main staging directory is renamed on completion, so callbacks must
    never expose paths into it to an in-flight model request.
    """
    parent = output.parent / f"{output.name}_source_ready"
    parent.mkdir(exist_ok=True)
    target = parent / source
    temporary = Path(tempfile.mkdtemp(prefix=f".{source}-", dir=parent))
    try:
        for asset in assets:
            for field in ("asset_path", "mask_path"):
                relative = asset.get(field)
                if relative:
                    destination = temporary / str(relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(stage / str(relative), destination)
        _write_json(temporary / "catalog.json", {
            "schema": _CATALOG_SCHEMA,
            "original_sha256": original_sha256,
            "canonical_sha256": canonical_sha256,
            "image_size": list(image_size), "assets": list(assets),
        })
        _write_json(temporary / "manifest.json", {"files": _inventory(temporary)})
        if target.exists():
            raise ValueError("source-ready evidence already exists; use a fresh run")
        os.replace(temporary, target)
        _fsync_directory(parent)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target / "catalog.json"


def canonical_original_snapshot(path: Path) -> tuple[Path, str, Image.Image, bytes]:
    """Return the one canonical RGB PNG snapshot used by capture and recovery."""
    requested = Path(path).expanduser()
    if requested.is_symlink() or not requested.is_file():
        raise ValueError("ORIGINAL must be a regular, non-symlink image file")
    original = requested.resolve(strict=True)
    try:
        source_bytes = original.read_bytes()
        with Image.open(BytesIO(source_bytes)) as source:
            transposed = ImageOps.exif_transpose(source)
            rgba = transposed.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            background.alpha_composite(rgba)
            canonical = background.convert("RGB")
            canonical.load()
    except (OSError, ValueError) as error:
        raise ValueError("ORIGINAL must be a readable raster image") from error
    buffer = BytesIO()
    canonical.save(buffer, format="PNG")
    return original, hashlib.sha256(source_bytes).hexdigest(), canonical, buffer.getvalue()


def _new_output_path(path: Path) -> Path:
    requested = Path(path).expanduser()
    if requested.exists() or requested.is_symlink():
        raise ValueError("raw evidence output_dir must not already exist")
    requested.parent.mkdir(parents=True, exist_ok=True)
    parent = requested.parent.resolve(strict=True)
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("raw evidence output parent must be a regular directory")
    if requested.name in {"", ".", ".."}:
        raise ValueError("raw evidence output_dir must have a safe final component")
    return parent / requested.name


def _persist_sam(
    stage: Path,
    response: Mapping[str, Any],
    canonical: Image.Image,
    image_size: tuple[int, int],
) -> list[dict[str, Any]]:
    _write_json(stage / "sam/response.raw.json", response)
    raw_regions = response.get("raw_regions")
    if not isinstance(raw_regions, list):
        raise ValueError("SAM response must contain raw_regions")
    _write_json(stage / "sam/raw_regions.json", raw_regions)
    response_artifacts = response.get("artifacts")
    if not isinstance(response_artifacts, Mapping):
        raise ValueError("SAM response must contain artifacts.mask_dir")
    mask_dir_value = response_artifacts.get("mask_dir")
    if not isinstance(mask_dir_value, str) or not mask_dir_value.strip():
        raise ValueError("SAM response must contain artifacts.mask_dir")
    requested_mask_root = Path(mask_dir_value).expanduser()
    if requested_mask_root.is_symlink() or not requested_mask_root.is_dir():
        raise ValueError("SAM mask_dir must be a regular, non-symlink directory")
    mask_root = requested_mask_root.resolve(strict=True)
    mask_snapshots: dict[int, bytes] = {}
    for index, entry in enumerate(raw_regions):
        if not isinstance(entry, Mapping):
            continue
        mask_value = _region_mask_path(entry)
        if mask_value is None:
            continue
        source_mask = _runtime_mask(mask_root, mask_value)
        try:
            mask_bytes = source_mask.read_bytes()
        except OSError as error:
            raise ValueError("SAM mask is unreadable") from error
        _validate_mask_bytes(mask_bytes, image_size)
        mask_snapshots[index] = mask_bytes
    copied_masks: dict[int, Path] = {}
    for index, mask_bytes in mask_snapshots.items():
        copied_mask = stage / "sam/masks" / f"sam-mask-{index:06d}.png"
        _write_bytes(copied_mask, mask_bytes)
        copied_masks[index] = copied_mask

    assets: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_regions):
        if not isinstance(entry, Mapping):
            continue
        raw_bbox = _bounded_bbox(entry.get("bbox", _geometry_bbox(entry)), image_size)
        if raw_bbox is None:
            continue
        copied_mask = copied_masks.get(index)
        if copied_mask is None:
            raise ValueError("valid SAM region is missing its full-canvas mask")
        with Image.open(copied_mask) as mask:
            alpha = mask.convert("L")
            local_alpha_bbox = alpha.crop(raw_bbox).getbbox()
            if local_alpha_bbox is None:
                continue
            bbox = (
                raw_bbox[0] + local_alpha_bbox[0],
                raw_bbox[1] + local_alpha_bbox[1],
                raw_bbox[0] + local_alpha_bbox[2],
                raw_bbox[1] + local_alpha_bbox[3],
            )
            rgba = canonical.convert("RGBA")
            rgba.putalpha(alpha)
            crop = rgba.crop(bbox)
        asset_id = f"sam-region-{index:06d}"
        crop_path = stage / "sam/crops" / f"{asset_id}.png"
        _save_png(crop, crop_path)
        prompt = str(entry.get("prompt", entry.get("source_prompt", "")))
        object_type = str(entry.get("object_type", entry.get("prompt_id", entry.get("label", ""))))
        assets.append({
            "asset_id": asset_id,
            "kind": "sam_region",
            "bbox": list(bbox),
            "prompt": prompt,
            "object_type": object_type,
            "semantic_anchor": str(entry.get("semantic_anchor", prompt)),
            "mask_path": copied_mask.relative_to(stage).as_posix(),
            "asset_path": crop_path.relative_to(stage).as_posix(),
            "sha256": _file_sha256(crop_path),
            "mask_sha256": _file_sha256(copied_mask),
            "source_index": index,
        })
    return assets


def _persist_ocr(
    stage: Path,
    response: Mapping[str, Any],
    canonical: Image.Image,
    image_size: tuple[int, int],
) -> list[dict[str, Any]]:
    _write_json(stage / "ocr/response.raw.json", response)
    boxes = response.get("boxes", response.get("ocr_text_boxes"))
    if not isinstance(boxes, list):
        raise ValueError("OCR response must contain boxes")
    assets: list[dict[str, Any]] = []
    for index, entry in enumerate(boxes):
        if not isinstance(entry, Mapping):
            continue
        bbox = _bounded_bbox(entry.get("bbox", entry.get("box")), image_size)
        if bbox is None:
            continue
        asset_id = f"ocr-box-{index:06d}"
        crop_path = stage / "ocr/crops" / f"{asset_id}.png"
        _save_png(canonical.convert("RGBA").crop(bbox), crop_path)
        text = str(entry.get("text", ""))
        assets.append({
            "asset_id": asset_id,
            "kind": "ocr_region",
            "bbox": list(bbox),
            "text": text,
            "semantic_anchor": text,
            "asset_path": crop_path.relative_to(stage).as_posix(),
            "sha256": _file_sha256(crop_path),
            "source_index": index,
        })
    return assets


def _preview_ocr_assets(
    response: Mapping[str, Any], image_size: tuple[int, int]
) -> list[dict[str, Any]]:
    """Expose OCR text and boxes immediately without publishing staged paths."""

    boxes = response.get("boxes", response.get("ocr_text_boxes"))
    if not isinstance(boxes, list):
        raise ValueError("OCR response must contain boxes")
    assets: list[dict[str, Any]] = []
    for index, entry in enumerate(boxes):
        if not isinstance(entry, Mapping):
            continue
        bbox = _bounded_bbox(entry.get("bbox", entry.get("box")), image_size)
        if bbox is None:
            continue
        text = str(entry.get("text", ""))
        assets.append({
            "asset_id": f"ocr-box-{index:06d}",
            "kind": "ocr_region",
            "bbox": list(bbox),
            "text": text,
            "semantic_anchor": text,
            "source_index": index,
        })
    return assets


def _source_ready_assets(
    source: str,
    response: Mapping[str, Any],
    worker_assets: Sequence[Mapping[str, Any]],
    image_size: tuple[int, int],
) -> tuple[Mapping[str, Any], ...]:
    """Build path-free callback data before declaring one source available."""

    if source == "sam":
        assets = worker_assets
    elif source == "ocr":
        assets = _preview_ocr_assets(response, image_size)
    elif source == "rmbg":
        assets = ()
    else:  # Defensive: collector owns the complete source namespace.
        raise ValueError(f"unknown raw evidence source: {source}")
    return tuple(dict(item) for item in assets)


def _persist_rmbg(
    stage: Path, response: Mapping[str, Any], image_size: tuple[int, int]
) -> dict[str, Any]:
    encoded = response.get("image_base64")
    if not isinstance(encoded, str):
        raise ValueError("RMBG response is missing image_base64")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(image_bytes)) as decoded:
            decoded.load()
            if decoded.mode != "RGBA":
                raise ValueError("RMBG output must be RGBA")
            if decoded.size != image_size:
                raise ValueError("RMBG output source size drift")
            image = decoded.copy()
    except (OSError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("RMBG"):
            raise
        raise ValueError("RMBG output is not a valid base64 image") from error
    path = stage / "rmbg/ORIGINAL.nobg.png"
    _save_png(image, path)
    return {
        "asset_id": "rmbg-full-000000",
        "kind": "rmbg_asset",
        "bbox": [0, 0, image_size[0], image_size[1]],
        "asset_path": path.relative_to(stage).as_posix(),
        "sha256": _file_sha256(path),
        "source_index": 0,
    }


def _region_mask_path(entry: Mapping[str, Any]) -> str | None:
    value = entry.get("mask_path")
    if isinstance(value, str) and value.strip():
        return value.strip()
    geometry = entry.get("geometry")
    if isinstance(geometry, Mapping):
        value = geometry.get("mask_path")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _geometry_bbox(entry: Mapping[str, Any]) -> Any:
    geometry = entry.get("geometry")
    return geometry.get("bbox") if isinstance(geometry, Mapping) else None


def _runtime_mask(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("SAM mask path escapes artifacts.mask_dir")
    parts = relative.parts
    # The local SAM service reports ``artifacts.mask_dir=/.../masks`` while
    # each region's path is rooted at the artifact directory (``masks/x``).
    # Remove only that exact duplicated directory component; all remaining
    # traversal and symlink checks stay confined beneath mask_dir.
    if len(parts) > 1 and parts[0] == root.name:
        parts = parts[1:]
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("SAM mask path must not contain symlinks")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ValueError("SAM mask path is missing or escapes artifacts.mask_dir") from error
    if not resolved.is_file():
        raise ValueError("SAM mask path is not a regular file")
    return resolved


def _validate_mask_bytes(payload: bytes, image_size: tuple[int, int]) -> None:
    try:
        with Image.open(BytesIO(payload)) as mask:
            mask.load()
            if mask.size != image_size:
                raise ValueError("SAM mask source size drift")
    except OSError as error:
        raise ValueError("SAM mask is not a readable image") from error


def _bounded_bbox(value: Any, image_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 4
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
            for item in value
        )
    ):
        return None
    bbox = (
        math.floor(value[0]), math.floor(value[1]),
        math.ceil(value[2]), math.ceil(value[3]),
    )
    if (
        bbox[0] < 0
        or bbox[1] < 0
        or bbox[0] >= bbox[2]
        or bbox[1] >= bbox[3]
        or bbox[2] > image_size[0]
        or bbox[3] > image_size[1]
    ):
        return None
    return bbox


def _remove_source_derivatives(stage: Path, source: str) -> None:
    if source == "sam":
        shutil.rmtree(stage / "sam/masks", ignore_errors=True)
        shutil.rmtree(stage / "sam/crops", ignore_errors=True)
    elif source == "ocr":
        shutil.rmtree(stage / "ocr/crops", ignore_errors=True)
    elif source == "rmbg":
        shutil.rmtree(stage / "rmbg", ignore_errors=True)


def _from_source(asset: Mapping[str, Any], source: str) -> bool:
    return asset.get("kind") == {
        "sam": "sam_region", "ocr": "ocr_region", "rmbg": "rmbg_asset"
    }[source]


def _inventory(root: Path) -> list[dict[str, Any]]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            files.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": _file_sha256(path),
                "size": path.stat().st_size,
            })
    return files


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: Any) -> None:
    _write_bytes(path, _json_bytes(payload))


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        image.save(handle, format="PNG")
        handle.flush()
        os.fsync(handle.fileno())


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return  # Directory-entry sync is POSIX-only; file data is already fsynced by callers.
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
