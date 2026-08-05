"""Session-level guard: transcribe.py 的 interpreter 自動切換（os.execv）絕不可在
pytest 內觸發 — 多 Python + MLX 環境下會把整個 pytest process 換成真實轉錄
（餵測試假檔 → MLX SIGABRT → exit 134）。

_honor_explicit_python 與 _maybe_reexec 兩條 execv 路徑都以 AUDIO_TLDR_REEXECED
為 loop guard，這裡設一次全部擋掉；要測 re-exec 行為的測試自行 monkeypatch.delenv。
"""
import os

os.environ["AUDIO_TLDR_REEXECED"] = "1"
os.environ.pop("AUDIO_TLDR_PYTHON", None)
