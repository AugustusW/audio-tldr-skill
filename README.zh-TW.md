# audio-tldr

> **任何影片、音檔、podcast → 重點摘要。本機轉錄，快取永存。**

[English](./README.md) | 繁體中文

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#前置準備)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-skill%20%2B%20plugin-orange.svg)](https://claude.com/claude-code)

一個 [Claude Code](https://claude.com/claude-code) skill：把長影音內容濃縮成 **3–7 條重點 + 一段摘要**。
轉錄用 whisper 在本機執行，以內容 hash 快取——同一來源**永遠不會轉錄第二次**；之後要求換角度重新摘要，
直接吃快取、幾秒完成。

> 一小時的 podcast 要轉錄十分鐘——但一輩子只需要這一次。

## 為什麼？

為了萃取 5 個重點看完 90 分鐘的演講，是一筆划不來的交易。把音訊丟上雲端 API 既花錢又外洩內容。
而同一集節目摘要兩次——因為第一次摘要的重點方向不對——等於轉錄成本再付一遍。

```text
沒有 audio-tldr                      有 audio-tldr
──────────────                      ─────────────
整部影片看完                          貼上網址
手動抄筆記                            拿到重點 + 摘要
「換個角度再摘一次…」                  吃快取重新 digest，秒回
重上傳、重轉錄、重新付費                轉錄一次，終身有效
```

## 特色

- ✓ YouTube、podcast、任何 yt-dlp 支援的網址——或本機影音檔
- ✓ 完全本機：下載、轉錄、快取，內容不離開你的電腦
- ✓ 內容 hash 快取：重新摘要（任何角度）永不重複轉錄
- ✓ whisper 後端自動偵測：mlx-whisper / faster-whisper / whisper.cpp / openai-whisper
- ✓ 語言自動偵測；中文可選配簡轉繁（OpenCC）
- ✓ 內建快取管理：列表、單清、全清、選配保留期限
- ✓ 超過 20 分鐘的內容附時間軸
- ✓ 手動 copy 或 Claude Code plugin 兩種安裝方式

## 安裝

**方式 A——直接複製 skill（最簡單）：**

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cp -r audio-tldr-skill/skills/audio-tldr ~/.claude/skills/
```

用 `/audio-tldr` 呼叫，或直接請 Claude 摘要影片——會自動觸發。

**方式 B——以 plugin 安裝：**

```
/plugin marketplace add AugustusW/audio-tldr-skill
/plugin install audio-tldr@audio-tldr-skill
```

用 `/audio-tldr:audio-tldr` 呼叫。兩種方式可並存——plugin skill 有獨立命名空間。

## 前置準備

全程本機執行，不上傳任何內容。

| 需求 | 用途 | 安裝 |
|---|---|---|
| Python 3.9+ | 執行轉錄腳本 | 通常已內建 |
| `yt-dlp` | 從網址下載音訊 | `pip install yt-dlp` 或 `brew install yt-dlp` |
| `ffmpeg` | 音訊抽取/轉檔 | `brew install ffmpeg` / `apt install ffmpeg` |
| **任選一個** whisper 後端 | 語音轉文字 | 見下表 |

whisper 後端（依自動偵測順序）：

| 後端 | 適合 | 安裝 | 預設模型 |
|---|---|---|---|
| [mlx-whisper](https://pypi.org/project/mlx-whisper/) | Apple Silicon（最快） | `pip install mlx-whisper` | `large-v3-turbo` |
| [faster-whisper](https://pypi.org/project/faster-whisper/) | 跨平台 GPU/CPU | `pip install faster-whisper` | `small` |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | CPU、零 Python 依賴 | `brew install whisper-cpp` + 設 `AUDIO_TLDR_WHISPER_CPP_MODEL` | （你指定的模型檔） |
| [openai-whisper](https://pypi.org/project/openai-whisper/) | 原版 CLI | `pip install openai-whisper` | `small` |

本機檔案不需要 `yt-dlp`，只要有 whisper 後端。

**選配——繁體中文**：whisper 對中文常輸出簡體。`pip install opencc` 之後，中文逐字稿自動轉台灣繁體
（並以 prompt 引導模型優先用繁體詞彙）；沒裝就維持原樣。

## 用法

```
> 幫我摘要 https://www.youtube.com/watch?v=xxxx
> 這集 podcast 的重點：https://podcasts.apple.com/...
> /audio-tldr ~/Downloads/會議錄音.m4a
> （稍後）同一部影片，只看定價相關的部分
```

最後一個直接吃快取——秒回，不重轉錄。

## 運作原理

刻意拆成兩段：

1. **轉錄**（`scripts/transcribe.py`）——算快取鍵（網址正規化或檔案內容 hash），命中直接秒回；
   未命中才 yt-dlp 下載 → 用最佳可用 whisper 後端轉錄 → 把 `transcript.txt` + `meta.json`
   存進 `~/.cache/audio-tldr/<sha256>/`。
2. **Digest**——Claude 讀快取逐字稿，產出重點、摘要、（長內容）大致時間軸。換角度重摘要完全跳過第一段。

## 快取與設定

快取**預設永久保留**——除非你主動設定，否則絕不自動刪除。

直接跟 Claude 說，或自己跑 `scripts/transcribe.py`：

| 指令 | 作用 |
|---|---|
| `--cache-info` | 列出快取逐字稿 + 大小（JSON） |
| `--clear "<來源>"` | 清除單筆 |
| `--clear-all --yes` | 全部清除 |
| `--set-retention <天數>` | 自動清除超過 N 天的項目（`off` = 回到永久保留） |
| `--force` | 忽略快取強制重轉錄 |

環境變數：

| 變數 | 用途 |
|---|---|
| `AUDIO_TLDR_MODEL` | 覆蓋目前後端的 whisper 模型 |
| `AUDIO_TLDR_WHISPER_CPP_MODEL` | ggml 模型檔路徑（啟用 whisper.cpp 後端） |
| `AUDIO_TLDR_ZH_CONVERT` | 中文轉換：`off`，或任何 OpenCC 設定（預設 `s2tw`） |

## 開發

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cd audio-tldr-skill
python3 -m pytest tests/   # 18 個單元測試，不需網路或模型
```

## 狀態

v0.1.0——核心流程（轉錄 → 快取 → digest）、四個 whisper 後端、中文轉換、快取管理均已完成並通過
端對端測試。可能的下一步：SRT 字幕匯出、講者分離。歡迎開 issue 與 PR。

## 授權

MIT。見 [LICENSE](./LICENSE)。

---

> 長內容值得聽一次——由你的電腦聽，不是你。
