"""A stand-in for Ollama 0.33.2's /api/chat context behaviour (measured 2026-10-11)."""
import io
import json
import re
import urllib.error
from pathlib import Path

MARK = re.compile(r"【標記:[^】]*】")


def default_reply(messages):
    seen = MARK.findall("\n".join(m["content"] for m in messages))
    return "SEEN: " + " ".join(seen) if seen else "SEEN: (none)"


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


REAL_400 = (Path(__file__).parent / "fixtures" / "ollama_0_33_2_exceed_400.json").read_text(encoding="utf-8").strip()


class FakeOllama:
    def __init__(self, n_ctx_default=8192, tokens_per_char=0.8, reply=default_reply, done_reason="stop",
                 honors_truncate=True, count=None, thinking_tokens=0):
        self.n_ctx_default, self.k, self.reply, self.done_reason = n_ctx_default, tokens_per_char, reply, done_reason
        self.honors_truncate = honors_truncate
        self.thinking_tokens = thinking_tokens  # tokens a thinking model spends out of num_predict unless think is false
        self.count = count  # optional callable(messages) -> tokens; default is chars * tokens_per_char
        self.requests = []
        self.prompt_evals = []  # the prompt_eval_count reported for each request

    def install(self, monkeypatch, module):
        monkeypatch.setattr(module.urllib.request, "urlopen", self.urlopen)

    def urlopen(self, req, timeout=None):
        body = json.loads(req.data.decode())
        if req.full_url.endswith("/api/show"):
            return _Resp({"model_info": {"general.architecture": "fake", "fake.context_length": 262144}})
        self.requests.append(body)
        msgs = [dict(m) for m in body["messages"]]
        n_ctx = (body.get("options") or {}).get("num_ctx", self.n_ctx_default)
        tokens = (self.count(msgs) if self.count else int(sum(len(m["content"]) for m in msgs) * self.k))
        if tokens > n_ctx:
            if body.get("truncate") is False and self.honors_truncate:
                inner = json.loads(json.loads(REAL_400)["error"])  # same shape as the real body
                inner["error"]["message"] = (f"request ({tokens} tokens) exceeds the available context size "
                                             f"({n_ctx} tokens), try increasing it")
                inner["error"]["n_prompt_tokens"], inner["error"]["n_ctx"] = tokens, n_ctx
                raw = json.dumps({"error": json.dumps(inner, separators=(",", ":"))}, separators=(",", ":"))
                raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(raw.encode()))
            keep = n_ctx // 2
            for m in msgs:
                if m["role"] == "user":
                    m["content"] = m["content"][-keep:]
            prompt_eval = keep + 3
        else:
            prompt_eval = tokens
        self.prompt_evals.append(prompt_eval)
        out = self.reply(msgs)
        done_reason = self.done_reason
        if self.thinking_tokens and body.get("think") is not False:
            room = (body.get("options") or {}).get("num_predict", 1 << 30) - self.thinking_tokens
            if room < len(out):  # thinking ate the reply budget: cut off with nothing usable
                out, done_reason = "", "length"
        return _Resp({"message": {"role": "assistant", "content": out}, "done_reason": done_reason,
                      "prompt_eval_count": prompt_eval, "eval_count": len(out)})
