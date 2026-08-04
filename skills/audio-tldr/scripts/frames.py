#!/usr/bin/env python3
"""audio-tldr frame extraction: scene-detect / timestamp -> jpg frames, cached."""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_t_spec = importlib.util.spec_from_file_location("_transcribe", _HERE / "transcribe.py")
_transcribe = importlib.util.module_from_spec(_t_spec)
_t_spec.loader.exec_module(_transcribe)
cache_key = _transcribe.cache_key
cache_dir = _transcribe.cache_dir
is_url = _transcribe.is_url


def parse_at_list(s: str) -> list:
    out = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if ":" in tok:
            parts = tok.split(":")
            if len(parts) not in (2, 3):
                raise ValueError(f"bad timestamp: {tok!r}")
            sec = 0.0
            for p in parts:
                sec = sec * 60 + float(p)
        else:
            sec = float(tok)
        if sec < 0:
            raise ValueError(f"negative timestamp: {tok!r}")
        out.append(sec)
    if not out:
        raise ValueError("empty --at list")
    return sorted(set(out))


def frame_filename(i: int, ts: float) -> str:
    m, s = int(ts) // 60, int(ts) % 60
    return f"{i:03d}-{m:04d}m{s:02d}s.jpg"
