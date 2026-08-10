"""Offline tests for scripts/digest.py — the Ollama local-digest bridge (v0.6.0).
No real Ollama server involved: urllib.request.urlopen is monkeypatched throughout,
same style as tests/test_transcribe.py monkeypatches subprocess.run."""
import io
import json
import sys
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "skills" / "audio-tldr" / "scripts" / "digest.py"
spec = importlib.util.spec_from_file_location("digest", SCRIPT)
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)


class _FakeResponse:
    """Minimal stand-in for the object urllib.request.urlopen() returns."""
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ── Endpoint resolution ───────────────────────────────────────────────

def test_resolve_ollama_host_default(monkeypatch):
    monkeypatch.delenv("AUDIO_TLDR_OLLAMA_HOST", raising=False)
    assert digest.resolve_ollama_host(None) == "http://localhost:11434"


def test_resolve_ollama_host_env_var(monkeypatch):
    monkeypatch.setenv("AUDIO_TLDR_OLLAMA_HOST", "http://box.local:11434/")
    assert digest.resolve_ollama_host(None) == "http://box.local:11434"  # trailing slash stripped


def test_resolve_ollama_host_cli_beats_env(monkeypatch):
    monkeypatch.setenv("AUDIO_TLDR_OLLAMA_HOST", "http://env-host:11434")
    assert digest.resolve_ollama_host("http://cli-host:11434") == "http://cli-host:11434"


# ── Prompt / message construction ───────────────────────────────────────

def test_build_messages_system_is_instructions_verbatim():
    msgs = digest.build_messages("SYSTEM RULES VERBATIM", "the transcript body")
    assert msgs[0] == {"role": "system", "content": "SYSTEM RULES VERBATIM"}


def test_build_messages_user_carries_transcript_and_untrusted_label():
    msgs = digest.build_messages("rules", "the transcript body")
    assert msgs[1]["role"] == "user"
    assert "the transcript body" in msgs[1]["content"]
    assert "untrusted" in msgs[1]["content"].lower()


# ── call_ollama_chat: request shape + response parsing ──────────────────

def test_call_ollama_chat_posts_expected_request_and_parses_content(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        captured["body"] = json.loads(req.data.decode())
        captured["timeout"] = timeout
        return _FakeResponse({
            "model": "llama3.2",
            "message": {"role": "assistant", "content": "the digest text"},
            "done": True,
        })

    monkeypatch.setattr(digest.urllib.request, "urlopen", fake_urlopen)
    out = digest.call_ollama_chat(
        "http://localhost:11434", "llama3.2",
        [{"role": "user", "content": "hi"}], timeout=30)

    assert out == "the digest text"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["body"] == {
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }
    assert captured["timeout"] == 30


def test_call_ollama_chat_strips_trailing_slash_from_host(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _FakeResponse({"message": {"content": "ok"}})

    monkeypatch.setattr(digest.urllib.request, "urlopen", fake_urlopen)
    digest.call_ollama_chat("http://localhost:11434/", "m", [], timeout=5)
    assert captured["url"] == "http://localhost:11434/api/chat"


def test_call_ollama_chat_malformed_response_raises_ollama_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return _FakeResponse({"done": True})  # no "message" / "content"

    monkeypatch.setattr(digest.urllib.request, "urlopen", fake_urlopen)
    try:
        digest.call_ollama_chat("http://localhost:11434", "m", [], timeout=5)
        assert False, "should raise"
    except digest.OllamaError as e:
        assert "unexpected" in str(e).lower()


# ── call_ollama_chat: honest error handling ──────────────────────────────

def test_call_ollama_chat_connection_refused_is_unreachable(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise digest.urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(digest.urllib.request, "urlopen", fake_urlopen)
    try:
        digest.call_ollama_chat("http://localhost:11434", "llama3.2", [], timeout=5)
        assert False, "should raise"
    except digest.OllamaUnreachable as e:
        assert "ollama serve" in str(e)
        assert "http://localhost:11434" in str(e)


def test_call_ollama_chat_timeout_is_unreachable(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(digest.urllib.request, "urlopen", fake_urlopen)
    try:
        digest.call_ollama_chat("http://localhost:11434", "llama3.2", [], timeout=5)
        assert False, "should raise"
    except digest.OllamaUnreachable as e:
        assert "timed out" in str(e).lower()
        assert "ollama serve" in str(e)


def test_call_ollama_chat_404_is_model_missing(monkeypatch):
    def fake_urlopen(req, timeout=None):
        body = json.dumps({"error": "model 'ghost:latest' not found, try pulling it first"}).encode()
        raise digest.urllib.error.HTTPError(req.full_url, 404, "Not Found", None, io.BytesIO(body))

    monkeypatch.setattr(digest.urllib.request, "urlopen", fake_urlopen)
    try:
        digest.call_ollama_chat("http://localhost:11434", "ghost:latest", [], timeout=5)
        assert False, "should raise"
    except digest.OllamaModelMissing as e:
        assert "ollama pull ghost:latest" in str(e)


def test_call_ollama_chat_other_http_error_is_generic_ollama_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise digest.urllib.error.HTTPError(
            req.full_url, 500, "Internal Server Error", None, io.BytesIO(b"boom"))

    monkeypatch.setattr(digest.urllib.request, "urlopen", fake_urlopen)
    try:
        digest.call_ollama_chat("http://localhost:11434", "m", [], timeout=5)
        assert False, "should raise"
    except digest.OllamaModelMissing:
        assert False, "500 must not be misclassified as model-missing"
    except digest.OllamaError as e:
        assert "500" in str(e)


# ── main(): end-to-end wiring ─────────────────────────────────────────

def test_main_success_prints_digest_and_reads_instructions_file(monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("hello world transcript")
    instructions = tmp_path / "instructions.txt"
    instructions.write_text("SYSTEM RULES")
    seen = {}

    def fake_call(host, model, messages, timeout=1800):
        seen["host"], seen["model"], seen["messages"] = host, model, messages
        return "THE DIGEST"

    monkeypatch.setattr(digest, "call_ollama_chat", fake_call)
    rc = digest.main([str(transcript), "--model", "llama3.2",
                      "--instructions-file", str(instructions)])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "THE DIGEST"
    assert seen["model"] == "llama3.2"
    assert seen["messages"][0]["content"] == "SYSTEM RULES"
    assert "hello world transcript" in seen["messages"][1]["content"]


def test_main_reads_instructions_from_stdin_when_no_file_given(monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("hi")
    monkeypatch.setattr(sys, "stdin", io.StringIO("STDIN RULES"))
    seen = {}

    def fake_call(host, model, messages, timeout=1800):
        seen["sys"] = messages[0]["content"]
        return "OK"

    monkeypatch.setattr(digest, "call_ollama_chat", fake_call)
    rc = digest.main([str(transcript), "--model", "llama3.2"])
    assert rc == 0 and seen["sys"] == "STDIN RULES"


def test_main_missing_transcript_exits_2(tmp_path, capsys):
    rc = digest.main([str(tmp_path / "nope.txt"), "--model", "llama3.2",
                      "--instructions-file", str(tmp_path / "i.txt")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "transcript not found" in captured.err


def test_main_missing_instructions_file_exits_2(tmp_path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("hi")
    rc = digest.main([str(transcript), "--model", "llama3.2",
                      "--instructions-file", str(tmp_path / "nope.txt")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "instructions file not found" in captured.err


def test_main_blank_instructions_exits_2(monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("hi")
    monkeypatch.setattr(sys, "stdin", io.StringIO("   \n  "))
    rc = digest.main([str(transcript), "--model", "llama3.2"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "instructions" in captured.err.lower()


def test_main_ollama_error_surfaces_on_stderr_and_never_prints_a_fallback_digest(
        monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("hi")
    instructions = tmp_path / "i.txt"
    instructions.write_text("rules")

    def boom(host, model, messages, timeout=1800):
        raise digest.OllamaUnreachable(
            "Ollama unreachable at http://localhost:11434 — is `ollama serve` running? (refused)")

    monkeypatch.setattr(digest, "call_ollama_chat", boom)
    rc = digest.main([str(transcript), "--model", "llama3.2",
                      "--instructions-file", str(instructions)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "ollama serve" in captured.err
    assert captured.out == ""  # no silent fallback text ever printed to stdout


def test_main_passes_ollama_host_flag_through(monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("hi")
    instructions = tmp_path / "i.txt"
    instructions.write_text("rules")
    seen = {}

    def fake_call(host, model, messages, timeout=1800):
        seen["host"] = host
        return "ok"

    monkeypatch.setattr(digest, "call_ollama_chat", fake_call)
    rc = digest.main([str(transcript), "--model", "llama3.2",
                      "--instructions-file", str(instructions),
                      "--ollama-host", "http://gpu-box:11434"])
    assert rc == 0 and seen["host"] == "http://gpu-box:11434"
