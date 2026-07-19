# audio-tldr

> **任何影片、音檔、podcast → 重點摘要。本機轉錄，快取永存。**

[English](./README.md) | 繁體中文

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#前置準備)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-skill%20%2B%20plugin-orange.svg)](https://claude.com/claude-code)
[![Codex](https://img.shields.io/badge/Codex-compatible-black.svg)](https://developers.openai.com/codex/skills)

一個 agent skill——採開放 [SKILL.md 標準](https://developers.openai.com/codex/skills)，
[Claude Code](https://claude.com/claude-code) 與 [Codex](https://developers.openai.com/codex/skills) **皆可用**——
把長影音內容濃縮成 **3–7 條重點 + 一段摘要**。
轉錄用 whisper 在本機執行，以內容 hash 快取——快取存在期間，同一來源**預設不會重新轉錄**
（除非 `--force`）；之後要求換角度重新摘要，直接吃快取、幾秒完成。

> 首次轉錄時間視硬體、模型與後端而定——之後交給快取回答。

## 為什麼？

為了萃取 5 個重點看完 90 分鐘的演講，是一筆划不來的交易。把音訊丟上雲端 API 既花錢又外洩內容。
而同一集節目摘要兩次——因為第一次摘要的重點方向不對——等於轉錄成本再付一遍。

```text
沒有 audio-tldr                      有 audio-tldr
──────────────                      ─────────────
整部影片看完                          貼上網址
手動抄筆記                            拿到重點 + 摘要
「換個角度再摘一次…」                  吃快取重新 digest，秒回
重上傳、重轉錄、重新付費                轉錄一次，後續重用快取
```

## 特色

- ✓ YouTube、podcast、任何 yt-dlp 支援的網址——或本機影音檔
- ✓ 媒體管線全本機：下載、轉錄、快取都在你的電腦上跑——音訊永不上傳（見[隱私](#隱私)）
- ✓ 內容 hash 快取：快取存在期間，重新摘要（任何角度）直接重用逐字稿
- ✓ whisper 後端自動偵測：mlx-whisper / faster-whisper / whisper.cpp / openai-whisper
- ✓ 語言自動偵測；中文可選配簡轉繁（OpenCC）
- ✓ 內建快取管理：列表、單清、全清、選配保留期限
- ✓ 超過 20 分鐘的內容附時間軸
- ✓ 摘要成品存入 output 資料夾，可選 Markdown 或 HTML——逐字稿留在快取
- ✓ 對話式詢問：請求沒說要怎麼整理時，agent 用純文字詢問（重點整理／會議記錄／詳細摘要／行動項目／Q&A／翻譯／自由描述）
- ✓ 摘要層翻譯：任何語言輸出摘要，或忠實全文翻譯
- ✓ 選配習慣設定檔——不設也能用，零門檻
- ✓ interpreter 自動選擇：backend 裝在別的 Python（如 homebrew）會自動找到並切換；`--doctor` 一鍵診斷環境
- ✓ 內建 Apple Podcasts fallback：yt-dlp extractor 失敗時自動走 iTunes lookup API——快取識別維持你貼的原始連結；貼節目頁連結（無單集 id）自動抓最新一集
- ✓ 手動 copy、Claude Code plugin、或裝進 Codex（開放 SKILL.md 標準）三種安裝方式

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

**方式 C——Codex CLI / ChatGPT app：**

本 skill 採開放 SKILL.md 標準，Codex 可直接使用。把 skill 資料夾複製進 Codex 的 skills 目錄：

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cp -r audio-tldr-skill/skills/audio-tldr ~/.codex/skills/audio-tldr        # 個人層
# 或專案層：cp -r audio-tldr-skill/skills/audio-tldr <repo>/.codex/skills/audio-tldr
```

用 `$audio-tldr` mention 呼叫，或直接請 Codex 摘要影音（描述命中會自動觸發）。逐字稿快取
（`~/.cache/audio-tldr/`）與習慣設定檔（`~/.config/audio-tldr/preferences.md`）跟 Claude Code
共用——轉錄一次，兩邊都能 digest。

## 前置準備

媒體管線——下載、轉錄、快取——全部在你的電腦上執行。

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

URL 來源請確認你有權下載與處理該內容，並遵守來源網站條款與當地著作權規範。

### 模型選擇

預設值偏保守（除 mlx 外都是 `small`，照顧 CPU 環境）。用 `AUDIO_TLDR_MODEL` 覆蓋——名稱須為目前後端支援的模型：

| 情境 | 建議模型 |
|---|---|
| CPU / 快速測試 | `small` |
| 一般中文摘要 | `medium` |
| 重視人名、專有名詞、精確度 | `large-v3` |
| 顯卡夠力、要速度與品質 | `large-v3` 或 `large-v3-turbo` |

```powershell
$env:AUDIO_TLDR_MODEL = "large-v3"    # PowerShell；bash/zsh 用 export AUDIO_TLDR_MODEL=large-v3
```

**選配——繁體中文**：whisper 對中文常輸出簡體。`pip install opencc` 之後，中文逐字稿自動轉台灣繁體
（並以 prompt 引導模型優先用繁體詞彙）；沒裝就維持原樣。

### Windows 注意事項

Windows 由底層 Python 生態支援並提供 PowerShell 安裝方式；**完整流程尚未在 Windows 上驗證**，
歡迎回報問題。用 PowerShell 安裝：

```powershell
# 前置準備（示範 winget；Chocolatey 用 choco install ffmpeg yt-dlp）
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp
py -3 -m pip install faster-whisper      # Windows 建議後端

# 安裝 skill（手動複製）
git clone https://github.com/AugustusW/audio-tldr-skill.git
$skillsDir = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
Copy-Item -Recurse -Force "audio-tldr-skill\skills\audio-tldr" $skillsDir
```

手動複製不會自動更新，且 `-Force` 會覆蓋既有的 `audio-tldr` 資料夾——想要版本管理請改用 plugin 安裝。

- **Python 指令**——`python3` 不存在時改用 `python` 或 py launcher（`py -3`）；skill 已指示
  Claude 自動改用，自己手動跑腳本時請對應替換。
- **Skill 路徑**——Windows 的 Claude Code 從 `%USERPROFILE%\.claude\skills\` 讀取 skill
  （plugin 安裝方式與 macOS/Linux 完全相同）。
- **GPU（選配）**——faster-whisper 預設 CPU 即可跑。NVIDIA 加速走 CTranslate2，先確認 CUDA 裝置可見：
  `py -3 -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"`。
  非零代表 CTranslate2 看得到 CUDA 裝置，但**不保證** CUDA runtime、cuBLAS/cuDNN DLL 與 GPU
  模型載入都完整——仍應實際執行一次短音訊轉錄確認。所需 CUDA/cuDNN 版本見
  [faster-whisper README](https://github.com/SYSTRAN/faster-whisper#gpu)。
- mlx-whisper 僅限 Apple Silicon；whisper.cpp 在 Windows 需要 PATH 上有 `whisper-cli.exe`
  並設 `AUDIO_TLDR_WHISPER_CPP_MODEL`。

## 用法

```
> 幫我摘要 https://www.youtube.com/watch?v=xxxx
> 這集 podcast 的重點：https://podcasts.apple.com/...
> /audio-tldr ~/Downloads/會議錄音.m4a
> 用新手聽得懂的方式摘要這場演講，只要行動清單：https://youtu.be/xxxx
> （稍後）同一部影片，只看定價相關的部分
```

在請求裡直接說明需求——聚焦主題、受眾、輸出格式、長度、語言——摘要就會照你的需求走，
而不是預設的重點+摘要結構。最後一個直接吃快取——秒回，不重轉錄。

## 運作原理

刻意拆成兩段：

1. **轉錄**（`scripts/transcribe.py`）——算快取鍵（網址正規化或檔案內容 hash），命中直接秒回；
   未命中才 yt-dlp 下載 → 用最佳可用 whisper 後端轉錄 → 把 `transcript.txt` + `meta.json`
   存進 `~/.cache/audio-tldr/<sha256>/`。
2. **Digest**——agent 讀快取逐字稿，產出重點、摘要、（長內容）大致時間軸。你的請求沒說要怎麼整理時，
   會先用**純對話文字**詢問（不出選單元件，透過通訊軟體純文字溝通也能用）。每份摘要同時存入
   output 資料夾（預設 `./audio-tldr-output/`），檔名 `<標題>-<日期>-<方式>.md`（或 `.html`）。
   換角度重摘要完全跳過第一段。

## 隱私

精確說清楚什麼留在本機、什麼不是：

- **音訊/影片永遠不離開你的電腦。** 不使用第三方語音轉錄服務，本 repo 的腳本也無遙測。網路連線只發生在
  合理位置：yt-dlp 會連來源網站下載 URL 內容、whisper 後端初次使用可能自模型庫下載模型（依賴套件的
  行為由各該專案自理）。
- **Digest 階段會把逐字稿文字（絕不是音訊）送進模型**——在你自己的 Claude session 內，跟請 Claude
  讀任何本機檔案完全一樣。
- **快取逐字稿是未加密純文字、預設永久保存**，位於 `~/.cache/audio-tldr/`。處理敏感內容後請 `--clear`
  該筆，或預先設定 retention。
- **摘要成品長存於 output 資料夾**（預設 `./audio-tldr-output/`，相對於工作目錄）——包含全文翻譯
  （等同整份逐字稿內容）。output 資料夾沒有清理或保留期限機制，請自行手動刪除；在 git 版控目錄內
  使用時建議把該資料夾加進 `.gitignore`。
- **只跑第一段（敏感錄音）**：自己執行腳本即可轉錄而不把文字交給 Claude——終端只輸出 metadata JSON，
  逐字稿留在回傳的 `transcript_path`，不把該路徑交給 Claude 就不會進入 digest：

  ```bash
  # macOS/Linux
  python3 ~/.claude/skills/audio-tldr/scripts/transcribe.py "/path/to/recording.m4a"
  ```

  ```powershell
  # Windows PowerShell
  py -3 "$env:USERPROFILE\.claude\skills\audio-tldr\scripts\transcribe.py" "C:\path\to\recording.m4a"
  ```

## 習慣設定（選配）

建立 `~/.config/audio-tldr/preferences.md` 記錄固定習慣——每個欄位都選填，不建檔一切照預設運作：

```markdown
output_dir: ~/Documents/audio-digests
timeline: off
auto_delete_audio: off
output_format: html
```

| 欄位 | 預設 | 說明 |
|---|---|---|
| `output_dir` | `./audio-tldr-output` | 摘要成品存放位置 |
| `timeline` | `on` | 內容夠長時在摘要附時間軸 |
| `auto_delete_audio` | `on` | 轉錄完刪除下載音檔；`off` 則 mp3 留在快取資料夾 |
| `output_format` | `md` | 摘要檔格式 `md` 或 `html`；當次對話指定優先於此欄 |

此檔由 agent 讀取（Claude Code 與 Codex 共用）——安裝時不會要求設定，檔案不存在時一律走預設。

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
| `--keep-audio` | 下載的 mp3 留在快取資料夾（預設轉錄完刪除） |
| `--doctor` | JSON 環境診斷：Python 路徑/版本、backend 與工具可見性、其他有 backend 的 interpreter、MLX Metal 可用性 |

環境變數：

| 變數 | 用途 |
|---|---|
| `AUDIO_TLDR_MODEL` | 覆蓋目前後端的 whisper 模型 |
| `AUDIO_TLDR_WHISPER_CPP_MODEL` | ggml 模型檔路徑（啟用 whisper.cpp 後端） |
| `AUDIO_TLDR_ZH_CONVERT` | 中文轉換：`off`，或任何 OpenCC 設定（預設 `s2tw`） |
| `AUDIO_TLDR_PYTHON` | 指定執行的 Python interpreter（優先於自動探測）。whisper backend 裝在非預設 Python（如 homebrew 3.12）時適用 |

## 開發

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cd audio-tldr-skill
python3 -m pytest tests/   # 39 個單元測試，不需網路或模型
```

版本規則：每次釋出必同步 bump `.claude-plugin/plugin.json` 與 `.claude-plugin/marketplace.json`
的 `version`（兩者保持一致），並在 [CHANGELOG](./CHANGELOG.md) 加一筆。

## 狀態

v0.3.0（[CHANGELOG](./CHANGELOG.md)）——核心邏輯有 39 個離線單元測試（yt-dlp、whisper 後端、
快取、OpenCC 皆以 mock 模擬，不需網路或模型）。完整流程於 2026-07-19 人工驗證
（真實 YouTube 下載、轉錄、快取重摘要、中文轉換、`--keep-audio`、output 資料夾 md/html 摘要、
逐字稿翻譯、從 `/usr/bin/python3` 的 interpreter 自動切換、Apple Podcasts fallback 端到端——
真實 53 分鐘節目經 iTunes lookup 解析、轉錄、原 Apple URL 二訪命中快取），環境如下：

| 元件 | 驗證版本 |
|---|---|
| macOS | 26.5.1（Apple M4 Pro） |
| Python | 3.12.13 |
| mlx-whisper | 0.4.3 |
| ffmpeg | 8.1 |
| yt-dlp | 2026.06.09 |

依賴更新後行為可能不同。尚無自動化測試涵蓋：真實下載、其餘三個後端、Windows 環境。
Codex 支援依開放 SKILL.md 標準；Codex 端的端到端驗證尚待完成。
可能的下一步：SRT 字幕匯出、講者分離。歡迎開 issue 與 PR。

## 授權

MIT。見 [LICENSE](./LICENSE)。

---

> 長內容值得聽一次——由你的電腦聽，不是你。
