"""Offline contract tests for the single OpenAI Responses attempt."""

import base64
import hashlib
import io
import json
from urllib.error import HTTPError

import pytest

from figfox_plus import providers


def _sse(*events):
    return io.BytesIO(b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events) + b"data: [DONE]\n\n")


def _call(tmp_path, send, **kwargs):
    return providers.call_gpt55(
        "Draw a fox", [], tmp_path / "attempt", "first-pass",
        send_http=send, ledger=tmp_path / "ledger.jsonl", **kwargs,
    )


def _records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_load_key_uses_process_then_explicit_file_then_project_files(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(providers, "PLUS_ROOT", project)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    external = tmp_path / "external.env"
    external.write_text('OPENAI_API_KEY="fixture-file-value"\n')
    monkeypatch.setenv("FLOW_ENV_FILE", str(external))
    assert providers.load_key("OPENAI_API_KEY") == "fixture-file-value"
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-process-value")
    assert providers.load_key("OPENAI_API_KEY") == "fixture-process-value"
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("FLOW_ENV_FILE")
    (project / ".env").write_text("OPENAI_API_KEY=fixture-env-value\n")
    (project / ".env.local").write_text("OPENAI_API_KEY=fixture-local-value\n")
    assert providers.load_key("OPENAI_API_KEY") == "fixture-local-value"


def test_missing_key_never_reads_legacy_script_or_records_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "PLUS_ROOT", tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FLOW_ENV_FILE", raising=False)
    (tmp_path / "output").mkdir()
    (tmp_path / "output/gpt55-once.py").write_text("OPENAI_API_KEY='fixture-legacy-value'\n")
    called = []
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda *a, **k: called.append(True))
    with pytest.raises(ValueError, match="missing credential OPENAI_API_KEY"):
        providers.call_gpt55("prompt", [], tmp_path / "run", "first", ledger=tmp_path / "ledger.jsonl")
    assert not called
    assert not (tmp_path / "ledger.jsonl").exists()


@pytest.mark.parametrize("setting", ["", "0", "128001", "3.5", "nope"])
def test_invalid_output_limit_fails_before_http_or_attempt(tmp_path, monkeypatch, setting):
    monkeypatch.setenv("FLOW_OPENAI_MAX_OUTPUT_TOKENS", setting)
    sent = []
    with pytest.raises(ValueError, match="FLOW_OPENAI_MAX_OUTPUT_TOKENS"):
        _call(tmp_path, lambda *a, **k: sent.append(True))
    assert not sent
    assert not (tmp_path / "ledger.jsonl").exists()


def test_sse_success_saves_exact_request_usage_and_timings(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOW_OPENAI_MODEL", "fixture-model")
    monkeypatch.setenv("FLOW_OPENAI_REASONING_EFFORT", "high")
    monkeypatch.setenv("FLOW_OPENAI_MAX_OUTPUT_TOKENS", "12345")
    jpeg = tmp_path / "mislabeled.png"
    jpeg_bytes = b"\xff\xd8\xff\xe0fixture-jpeg\xff\xd9"
    jpeg.write_bytes(jpeg_bytes)
    png = tmp_path / "image.jpg"
    png_bytes = b"\x89PNG\r\n\x1a\nfixture-png"
    png.write_bytes(png_bytes)
    seen = []

    def send(req, timeout):
        seen.append((req, timeout))
        return _sse(
            {"type": "response.output_text.delta", "delta": "<svg"},
            {"type": "response.output_text.delta", "delta": "></svg>"},
            {"type": "response.completed", "response": {"status": "completed", "usage": {"input_tokens": 19, "output_tokens": 7}}},
        )

    result = providers.call_gpt55("Draw a fox", [jpeg, png], tmp_path / "attempt", "first-pass", send_http=send, ledger=tmp_path / "ledger.jsonl")
    assert result == "<svg></svg>"
    assert len(seen) == 1
    req, timeout = seen[0]
    assert timeout == 1800
    body_bytes = req.data
    saved = json.loads((tmp_path / "attempt/request.json").read_text())
    assert saved["body"] == json.loads(body_bytes)
    assert saved["body_sha256"] == hashlib.sha256(body_bytes).hexdigest()
    assert saved["body"]["model"] == "fixture-model"
    assert saved["body"]["reasoning"] == {"effort": "high"}
    assert saved["body"]["max_output_tokens"] == 12345
    images = saved["body"]["input"][0]["content"][1:]
    assert images[0]["image_url"] == "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()
    assert images[1]["image_url"] == "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    assert "Authorization" not in (tmp_path / "attempt/request.json").read_text()
    assert json.loads((tmp_path / "attempt/usage.json").read_text())["input_tokens"] == 19
    timing = json.loads((tmp_path / "attempt/timings.json").read_text())
    assert timing["elapsed_seconds"] >= 0
    assert [r["event"] for r in _records(tmp_path / "ledger.jsonl")] == ["sending", "ok"]


@pytest.mark.parametrize("events,error", [
    ([{"type": "response.output_text.delta", "delta": "partial"}, {"type": "response.incomplete", "response": {"status": "incomplete", "usage": {"input_tokens": 2}}}], "incomplete"),
    ([{"type": "response.output_text.delta", "delta": "partial"}], "without completion"),
])
def test_incomplete_stream_keeps_raw_evidence_and_cannot_retry_same_dir(tmp_path, events, error):
    sent = []

    def send(req, timeout):
        sent.append(True)
        return _sse(*events)

    with pytest.raises(ValueError, match=error):
        _call(tmp_path, send)
    assert sent == [True]
    assert (tmp_path / "attempt/events.jsonl").exists()
    assert (tmp_path / "attempt/response.txt").read_text() == "partial"
    assert json.loads((tmp_path / "attempt/error.json").read_text())["type"] == "ValueError"
    assert [r["event"] for r in _records(tmp_path / "ledger.jsonl")] == ["sending", "error"]
    if "incomplete" in error:
        assert json.loads((tmp_path / "attempt/response.json").read_text())["status"] == "incomplete"
    with pytest.raises(ValueError, match="already attempted"):
        _call(tmp_path, send)
    assert sent == [True]


def test_http_error_is_single_attempt_and_error_details_are_redacted(tmp_path):
    sent = []

    def send(req, timeout):
        sent.append(True)
        raise HTTPError(req.full_url, 429, "fixture failure", {}, io.BytesIO(b'{"error":"fixture-http-error"}'))

    with pytest.raises(HTTPError):
        _call(tmp_path, send)
    assert sent == [True]
    error = json.loads((tmp_path / "attempt/error.json").read_text())
    assert error["http_status"] == 429
    assert "fixture-http-error" in error["details"]
    assert [r["event"] for r in _records(tmp_path / "ledger.jsonl")] == ["sending", "error"]
