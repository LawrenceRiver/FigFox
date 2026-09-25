#!/usr/bin/env python3
"""Expose fal.ai SAM3 through Crafter's local SAM3 HTTP contract."""
from __future__ import annotations

import base64
import csv
import io
import os
import subprocess
import tempfile
from pathlib import Path

import fal_client
import httpx
import numpy as np
from flask import Flask, jsonify, request
from PIL import Image


FAL_MODEL = "fal-ai/sam-3/image-rle"
FAL_MASK_SIZE = 1024
app = Flask(__name__)
_BASE_HTTPX_CLIENT = httpx.Client


def _direct_fal_http_client(*args, **kwargs) -> httpx.Client:
    """Create the HTTP client for fal without inheriting a broken proxy route."""
    kwargs["trust_env"] = False
    return _BASE_HTTPX_CLIENT(*args, **kwargs)


class _DirectCDNTokenManager(fal_client.client.CDNTokenManager):
    """Request fal upload tokens over the same explicit direct connection."""

    def _refresh_token(self):
        with _direct_fal_http_client() as client:
            response = client.post(self._url, headers=self._headers, json={})
            response.raise_for_status()
            data = response.json()
        return fal_client.client.CDNToken(
            token=data["token"],
            token_type=data["token_type"],
            base_upload_url=data["base_url"],
            expires_at=fal_client.client.datetime.fromisoformat(data["expires_at"]),
        )


def _configure_fal_direct_connection() -> None:
    """Keep all calls made by the module-level fal SDK client off proxy discovery."""
    if not (os.environ.get("FAL_KEY") or os.environ.get("FAL_KEY_ID")):
        return
    client = fal_client.sync_client
    auth = client._auth
    client.__dict__["_client"] = _direct_fal_http_client(
        headers={"Authorization": auth.header_value, "User-Agent": fal_client.client.USER_AGENT},
        timeout=client.default_timeout,
        follow_redirects=True,
    )
    client.__dict__["_token_manager"] = _DirectCDNTokenManager(auth)


_configure_fal_direct_connection()


def decode_fal_runs(encoded: str, width: int = FAL_MASK_SIZE, height: int = FAL_MASK_SIZE) -> np.ndarray:
    """Decode fal's whitespace-separated ``start length`` mask runs."""
    values = [int(value) for value in encoded.split()]
    if len(values) % 2:
        raise ValueError("fal RLE must contain start/length pairs")
    flat = np.zeros(width * height, dtype=bool)
    for start, length in zip(values[::2], values[1::2]):
        if length <= 0:
            continue
        left = max(0, start)
        right = min(flat.size, start + length)
        if left < right:
            flat[left:right] = True
    return flat.reshape((height, width))


def mask_result(mask: np.ndarray, input_box: list[int], confidence: float = 1.0) -> dict:
    """Format a boolean mask into Crafter's ``/segment_bbox`` record."""
    ys, xs = np.where(mask)
    if len(xs):
        tight = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    else:
        tight = list(input_box)
    payload = io.BytesIO()
    Image.fromarray(mask.astype(np.uint8) * 255).save(payload, format="PNG")
    return {
        "input_box": list(input_box),
        "tight_box": tight,
        "det_box": tight,
        "mask_b64": base64.b64encode(payload.getvalue()).decode("ascii"),
        "iou_score": 1.0,
        "confidence": round(float(confidence), 3),
        "mask_size": [int(mask.shape[1]), int(mask.shape[0])],
        "mask_pixels": int(mask.sum()),
    }


def _scaled_mask(encoded: str, width: int, height: int) -> np.ndarray:
    raw = decode_fal_runs(encoded)
    return np.array(
        Image.fromarray(raw.astype(np.uint8) * 255).resize(
            (width, height), Image.Resampling.NEAREST
        ),
        dtype=bool,
    )


def _box_from_normalized(box: list[float] | None, width: int, height: int) -> list[int] | None:
    if not box or len(box) != 4:
        return None
    cx, cy, bw, bh = box
    return [
        max(0, round((cx - bw / 2) * width)),
        max(0, round((cy - bh / 2) * height)),
        min(width, round((cx + bw / 2) * width)),
        min(height, round((cy + bh / 2) * height)),
    ]


def _segment(image_path: str, *, prompt: str | None = None, boxes: list[list[int]] | None = None) -> tuple[list[dict], tuple[int, int]]:
    with Image.open(image_path) as source:
        width, height = source.size
    arguments: dict = {
        "image_url": fal_client.upload_file(image_path),
        "include_boxes": True,
        "include_scores": True,
        "apply_mask": False,
    }
    if prompt:
        arguments["prompt"] = prompt
    if boxes:
        arguments["box_prompts"] = [
            {"x_min": box[0], "y_min": box[1], "x_max": box[2], "y_max": box[3], "object_id": index}
            for index, box in enumerate(boxes)
        ]
    try:
        response = fal_client.subscribe(FAL_MODEL, arguments=arguments)
    except Exception as error:
        if "No masks generated" in str(error):
            return [], (width, height)
        raise
    rles = response.get("rle", [])
    if isinstance(rles, str):
        rles = [rles]
    scores = response.get("scores") or []
    remote_boxes = response.get("boxes") or []
    results: list[dict] = []
    for index, encoded in enumerate(rles):
        if not encoded:
            continue
        mask = _scaled_mask(encoded, width, height)
        box = _box_from_normalized(remote_boxes[index] if index < len(remote_boxes) else None, width, height)
        if not box:
            ys, xs = np.where(mask)
            box = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else [0, 0, width, height]
        item = mask_result(mask, input_box=box, confidence=scores[index] if index < len(scores) else 1.0)
        results.append(item)
    return results, (width, height)


def _store_upload() -> Path:
    upload = request.files.get("image")
    if upload is None:
        raise ValueError("missing image upload")
    suffix = Path(upload.filename or "image.png").suffix or ".png"
    with tempfile.NamedTemporaryFile(prefix="crafter-sam3-", suffix=suffix, delete=False) as temp:
        upload.save(temp)
        return Path(temp.name)


def _store_base64_image(encoded: str, filename: str = "image.png") -> Path:
    """Persist DrawAI's JSON image payload long enough for a fal request."""
    raw = base64.b64decode(encoded, validate=True)
    suffix = Path(filename).suffix or ".png"
    with tempfile.NamedTemporaryFile(prefix="drawai-sam3-", suffix=suffix, delete=False) as temp:
        temp.write(raw)
        return Path(temp.name)


def tesseract_tsv_to_ocr_payload(tsv: str) -> dict:
    """Normalize Tesseract word boxes to DrawAI's remote PaddleOCR schema."""
    boxes: list[dict] = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
        text = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf") or -1)
            left = int(row.get("left") or 0)
            top = int(row.get("top") or 0)
            width = int(row.get("width") or 0)
            height = int(row.get("height") or 0)
        except ValueError:
            continue
        if not text or confidence < 0 or width <= 0 or height <= 0:
            continue
        boxes.append(
            {
                "id": f"tesseract_{len(boxes) + 1:03d}",
                "bbox": [left, top, left + width, top + height],
                "confidence": round(confidence / 100, 3),
                "source": "tesseract",
                "text": text,
            }
        )
    return {"ocr_text_boxes": boxes}


def _tesseract_ocr(image_path: Path) -> dict:
    completed = subprocess.run(
        ["tesseract", str(image_path), "stdout", "tsv"],
        check=True,
        text=True,
        capture_output=True,
    )
    return tesseract_tsv_to_ocr_payload(completed.stdout)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "model_loaded": bool(os.environ.get("FAL_KEY")), "device": "fal.ai/sam-3"})


@app.post("/segment")
def segment():
    path = _store_upload()
    try:
        prompts = [value.strip() for value in request.form.get("prompts", "icon").split(",") if value.strip()]
        boxes: list[dict] = []
        for prompt in prompts:
            results, _ = _segment(str(path), prompt=prompt)
            for item in results:
                x1, y1, x2, y2 = item["tight_box"]
                boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "score": item["confidence"], "prompt": prompt})
        return jsonify({"boxes": boxes})
    finally:
        path.unlink(missing_ok=True)


@app.post("/segment_bbox")
def segment_bbox():
    path = _store_upload()
    try:
        import json
        input_boxes = json.loads(request.form.get("boxes", "[]"))
        results, (width, height) = _segment(str(path), boxes=input_boxes)
        for index, item in enumerate(results):
            item["index"] = index
            if index < len(input_boxes):
                item["input_box"] = input_boxes[index]
        return jsonify({"results": results, "image_size": [width, height]})
    finally:
        path.unlink(missing_ok=True)


@app.post("/v1/segment/proposals")
def drawai_segment_proposals():
    """Translate DrawAI's JSON SAM3 contract into fal.ai SAM3 calls."""
    payload = request.get_json(force=True)
    encoded_image = payload.get("image_base64")
    if not isinstance(encoded_image, str) or not encoded_image:
        return jsonify({"detail": "image_base64 is required"}), 400
    prompts = payload.get("prompts")
    if not isinstance(prompts, list):
        return jsonify({"detail": "prompts must be a list"}), 400
    path = _store_base64_image(encoded_image)
    try:
        regions: list[dict] = []
        raw_regions: list[dict] = []
        for prompt in prompts:
            if not isinstance(prompt, dict):
                continue
            prompt_id = str(prompt.get("id") or prompt.get("text") or "unknown")
            prompt_text = str(prompt.get("text") or prompt_id)
            threshold = float(prompt.get("confidence_threshold") or 0.0)
            results, _ = _segment(str(path), prompt=prompt_text)
            for result in results:
                score = float(result["confidence"])
                if score < threshold:
                    continue
                bbox = list(result["tight_box"])
                regions.append({"bbox": bbox, "score": score, "label": prompt_id})
                raw_regions.append(
                    {
                        "bbox": bbox,
                        "score": score,
                        "label": prompt_id,
                        "source_prompt": prompt_id,
                    }
                )
        return jsonify({"regions": regions, "raw_regions": raw_regions, "artifacts": {}})
    except (ValueError, TypeError) as error:
        return jsonify({"detail": str(error)}), 400
    finally:
        path.unlink(missing_ok=True)


@app.post("/v1/ocr/boxes")
def drawai_ocr_boxes():
    """Provide real local OCR boxes using the schema DrawAI expects from PaddleOCR."""
    payload = request.get_json(force=True)
    encoded_image = payload.get("image_base64")
    if not isinstance(encoded_image, str) or not encoded_image:
        return jsonify({"detail": "image_base64 is required"}), 400
    path = _store_base64_image(encoded_image, str(payload.get("filename") or "image.png"))
    try:
        return jsonify(_tesseract_ocr(path))
    except subprocess.CalledProcessError as error:
        return jsonify({"detail": error.stderr.strip() or "tesseract failed"}), 500
    except (ValueError, TypeError) as error:
        return jsonify({"detail": str(error)}), 400
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), debug=False)
