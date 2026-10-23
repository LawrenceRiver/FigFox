"""Local crop and replacement contract; all images are generated in the test."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from figfox_plus.native import pipeline, sam_replace, tools


def picture(tmp_path):
    path = tmp_path / "original.png"
    im = Image.new("RGB", (16, 16), "white")
    im.putpixel((3, 3), (23, 45, 67))
    im.save(path)
    return path


def svg(body):
    return ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">' + body + '</svg>')


def asset_op(**args):
    return {"id": "crop_host", "issue_id": "issue", "action": "asset", "target_ids": ["replacement"],
            "args": {"source_crop": [2, 2, 4, 4], "target_box": [2, 2, 4, 4],
                     "classification": "complex_geometry", **args}}


def test_default_crop_preserves_background_and_explicit_removal_is_strict(tmp_path, monkeypatch):
    original = picture(tmp_path)
    root = svg('<g id="replacement"><rect x="2" y="2" width="4" height="4"/></g>')
    calls = []
    def remove(asset, out):
        calls.append(asset)
        return asset
    monkeypatch.setattr(tools, "remove_background_asset", remove)
    for flag in (None, False):
        args = {"classification": "photo", "source_crop": [2, 2, 4, 4], "target_box": [2, 2, 4, 4]}
        if flag is not None: args["remove_background"] = flag
        op = {**asset_op(), "args": args}
        result, _ = tools.execute(root, [op], [{"id": "issue", "target_ids": ["replacement"]}], original, tmp_path / "run")
        href = next(n.get("href") for n in result.iter() if n.tag.endswith("image"))
        from io import BytesIO
        with Image.open(BytesIO(base64.b64decode(href.split(",", 1)[1]))) as im:
            assert im.convert("RGB").getpixel((0, 0)) == (255, 255, 255)
    assert calls == []
    tools.execute(root, [{**asset_op(), "args": {**asset_op()["args"], "classification": "photo", "remove_background": True}}],
                  [{"id": "issue", "target_ids": ["replacement"]}], original, tmp_path / "remove")
    assert len(calls) == 1
    for invalid in ("true", 1, None, []):
        with pytest.raises(ValueError, match="remove_background"):
            tools.execute(root, [{**asset_op(), "args": {**asset_op()["args"], "remove_background": invalid}}],
                          [{"id": "issue", "target_ids": ["replacement"]}], original, tmp_path / "bad")


def test_real_first_crop_pixelruns_removes_declared_draft(tmp_path):
    original = picture(tmp_path)
    response = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><g id="draft"><rect x="2" y="2" width="4" height="4"/></g><g id="replacement" data-plus-crop="2,2,4,4" data-plus-backend="pixelruns" data-plus-replaces="draft" data-plus-keeps="keep" data-plus-covered-frames="frame"/><text id="keep" x="1" y="12">keep</text></svg>'
    run = tmp_path / "first"
    run.mkdir()
    root = pipeline.first(original, run, send=lambda *unused: response, sam={"assets": []})
    ids = tools.nodes(root)
    assert "draft" not in ids
    assert "replacement" in ids and "keep" in ids
    assert any(n.tag.endswith("path") for n in ids["replacement"].iter())
    assert ids["replacement"].get("data-plus-keeps") == "keep"
    assert json.loads((run / "first-sam-replacement.json").read_text())[0]["removed_draft_ids"] == ["draft"]


@pytest.mark.parametrize("host_crop", [False, True])
def test_first_requires_coverage_for_frame_inside_replaced_draft(tmp_path, host_crop):
    original = picture(tmp_path)
    crop = ' data-plus-crop="2,2,4,4" data-plus-backend="pixelruns"' if host_crop else ''
    response = ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
                '<g id="draft"><g id="frame" data-plus-kind="frame"' + crop + '><rect x="2" y="2" width="4" height="4"/></g></g>'
                '<g id="replacement" data-plus-crop="2,2,4,4" data-plus-backend="pixelruns" data-plus-replaces="draft"/>'
                '</svg>')
    run = tmp_path / "first"
    run.mkdir()
    with pytest.raises(ValueError, match="frame coverage must be explicit"):
        pipeline.first(original, run, send=lambda *unused: response, sam={"assets": []})


def test_first_accepts_explicit_coverage_for_host_cropped_frame(tmp_path):
    original = picture(tmp_path)
    response = ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
                '<g id="draft"><g id="frame" data-plus-kind="frame" data-plus-crop="2,2,4,4" data-plus-backend="pixelruns"/></g>'
                '<g id="replacement" data-plus-crop="2,2,4,4" data-plus-backend="pixelruns" data-plus-replaces="draft" data-plus-covered-frames="frame"/>'
                '</svg>')
    run = tmp_path / "first"
    run.mkdir()
    root = pipeline.first(original, run, send=lambda *unused: response, sam={"assets": []})
    assert "draft" not in tools.nodes(root)
    assert json.loads((run / "first-sam-replacement.json").read_text())[0]["covered_frame_ids"] == ["frame"]


@pytest.mark.parametrize("covered", [False, True])
def test_first_keeps_frame_coverage_when_crop_replaces_its_parent(tmp_path, covered):
    original = picture(tmp_path)
    coverage = ' data-plus-covered-frames="frame"' if covered else ''
    response = ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
                '<g id="draft"><g id="crop_parent" data-plus-crop="2,2,4,4" data-plus-backend="pixelruns">'
                '<rect id="frame" data-plus-kind="frame" x="2" y="2" width="4" height="4"/></g></g>'
                '<g id="replacement" data-plus-crop="2,2,4,4" data-plus-backend="pixelruns" data-plus-replaces="draft"' + coverage + '/>'
                '</svg>')
    run = tmp_path / "first"
    run.mkdir()
    if covered:
        root = pipeline.first(original, run, send=lambda *unused: response, sam={"assets": []})
        assert "draft" not in tools.nodes(root)
    else:
        with pytest.raises(ValueError, match="frame coverage must be explicit"):
            pipeline.first(original, run, send=lambda *unused: response, sam={"assets": []})


def test_unverified_vector_cannot_delete_draft():
    root = svg('<g id="draft"><rect width="4" height="4"/></g><g id="replacement" data-plus-replaces="draft"><path d="M0 0h4v4z"/></g>')
    before = ET.tostring(root)
    with pytest.raises(ValueError, match="authenticated host crop"):
        sam_replace.apply_replacements(root)
    assert ET.tostring(root) == before


def test_host_crop_proof_binds_node_file_source_and_declaration(tmp_path):
    original = picture(tmp_path)
    root = svg('<g id="draft"><rect width="4" height="4"/></g><g id="replacement" data-plus-replaces="draft" data-plus-keeps="keep"><rect x="2" y="2" width="4" height="4"/></g><text id="keep">keep</text>')
    result, logs = tools.execute(root, [asset_op(backend="pixelruns")],
                                 [{"id": "issue", "target_ids": ["replacement"]}], original, tmp_path / "host")
    node = tools.nodes(result)["replacement"]
    node.set("data-plus-replaces", "draft")
    node.set("data-plus-keeps", "keep")
    proof = pipeline._host_crop_proof(node, logs[0]["result"], original, [2, 2, 4, 4], tmp_path / "host")
    assert sam_replace.apply_replacements(deepcopy(result), {"replacement": proof})[0]["removed_draft_ids"] == ["draft"]
    for key, value in (("data-plus-replaces", "other"), ("transform", "translate(2 0)"), ("data-plus-keeps", "draft")):
        changed = deepcopy(result)
        tools.nodes(changed)["replacement"].set(key, value)
        with pytest.raises(ValueError, match="authenticated host crop"):
            sam_replace.apply_replacements(changed, {"replacement": proof})
    asset_path = Path(proof["asset_path"])
    saved = asset_path.read_bytes()
    try:
        asset_path.write_bytes(saved + b"tamper")
        with pytest.raises(ValueError, match="authenticated host crop"):
            sam_replace.apply_replacements(deepcopy(result), {"replacement": proof})
    finally:
        asset_path.write_bytes(saved)
    original.write_bytes(original.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="authenticated host crop"):
        sam_replace.apply_replacements(deepcopy(result), {"replacement": proof})


@pytest.mark.parametrize("body,message", [
    ('<g id="draft"><rect/></g><g id="replacement" data-plus-replaces="missing"><image href="data:image/png;base64,AA=="/></g>', "unresolved_missing_draft"),
    ('<g id="draft"><rect/></g><g id="replacement" data-plus-replaces="draft draft"><image href="data:image/png;base64,AA=="/></g>', "invalid or duplicate replacement target"),
    ('<g id="draft"><rect id="frame" data-plus-kind="frame"/></g><g id="replacement" data-plus-replaces="draft"><image href="data:image/png;base64,AA=="/></g>', "frame coverage must be explicit"),
    ('<g id="draft"><rect/><g id="child"><path/></g></g><g id="replacement" data-plus-replaces="draft child"><image href="data:image/png;base64,AA=="/></g>', "overlapping replacement targets"),
    ('<g id="draft"><path id="keep"/></g><g id="replacement" data-plus-replaces="draft" data-plus-keeps="keep"><image href="data:image/png;base64,AA=="/></g>', "replacement would delete protected object"),
])
def test_original_replacement_protections_remain(body, message):
    root = svg(body)
    before = ET.tostring(root)
    if message == "unresolved_missing_draft":
        assert sam_replace.apply_replacements(root)[0]["status"] == message
    else:
        with pytest.raises(ValueError, match=message):
            sam_replace.apply_replacements(root)
        assert ET.tostring(root) == before


def test_asset_rejects_unregistered_backend(tmp_path):
    original = picture(tmp_path)
    root = svg('<g id="replacement"><rect x="2" y="2" width="4" height="4"/></g>')
    with pytest.raises(ValueError, match="backend"):
        tools.execute(root, [asset_op(backend="arbitrary")],
                      [{"id": "issue", "target_ids": ["replacement"]}], original, tmp_path / "run")
