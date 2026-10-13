# audio-tldr

> **任何影片、音檔、podcast → 重點摘要。本機轉錄，快取永存。**

[English](./README.md) | 繁體中文

[![Release](https://img.shields.io/github/v/release/AugustusW/audio-tldr-skill?color=brightgreen)](https://github.com/AugustusW/audio-tldr-skill/releases)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#前置準備)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-skill%20%2B%20plugin-orange.svg)](https://claude.com/claude-code)
[![Codex](https://img.shields.io/badge/Codex-compatible-black.svg)](https://developers.openai.com/codex/skills)

![示範：從快取轉錄稿摘要 YouTube 影片](./assets/demo.gif)

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
- ✓ 對話式詢問：請求沒說要怎麼整理時，agent 用純文字列出樣板選單詢問
- ✓ 整理樣板：會議記錄／重點摘要／分析報告——也可把自己的格式存成樣板重用
- ✓ 選配全本機摘要：`digest_model: ollama:<model>` 讓第二階段改走你自己的 Ollama server——逐字稿文字也不離開電腦
- ✓ 摘要層翻譯：任何語言輸出摘要，或忠實全文翻譯
- ✓ 選配習慣設定檔——不設也能用，零門檻
- ✓ interpreter 自動選擇：backend 裝在別的 Python（如 homebrew）會自動找到並切換；`--doctor` 一鍵診斷環境
- ✓ 內建 Apple Podcasts fallback：yt-dlp extractor 失敗時自動走 iTunes lookup API——快取識別維持你貼的原始連結；貼節目頁連結（無單集 id）自動抓最新一集
- ✓ 影片來源可選抽幀：scene detection 投影片截圖、或指定時間戳畫面——影片以 ≤720p 抓取、抽完即刪；幀圖與逐字稿共用同一快取 entry
- ✓ 字幕匯出：`--format srt` / `--format vtt` 產出含時間戳的標準字幕檔，與逐字稿並存，四個後端皆支援
- ✓ 逐字稿校正：摘要前由模型提出讀音相近的修改，`correct.py` 檢查後套用到快取的副本；原本的逐字稿不會被修改（選配 `pypinyin`、`jellyfish`）
- ✓ 名詞校正：發音跟別的詞一樣的名字（真真被轉成珍珍），在摘要時依來源自己的標題、頻道、節目／頻道作者、說明欄、章節、tags，加上可選的 glossary 改回來；每一處修改都會列出，逐字稿本身不動
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

本 skill 採開放 SKILL.md 標準，Codex 可直接使用。Codex 的 plugin 指令讀同一個 marketplace
（在終端機執行，不是在 Codex 對話裡）：

```bash
codex plugin marketplace add AugustusW/audio-tldr-skill
codex plugin add audio-tldr@audio-tldr-skill
```

這樣裝的 skill 名稱是 `audio-tldr:audio-tldr`（以 codex-cli 0.162.1 確認過：裝得起來、Codex
列得出這個 skill；1.0 發版前的 Codex 端到端實測用的是下面的複製方式）。或者把 skill 資料夾複製進
Codex 的 skills 目錄：

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
| Python 3.10+ | 執行轉錄腳本 | macOS 內建的 `python3` 是 3.9，不在支援範圍：`brew install python` 或 `uv python install 3.12`；Windows 用 python.org 安裝檔 |
| `yt-dlp` | 從網址下載音訊 | `pip install yt-dlp` 或 `brew install yt-dlp` |
| `ffmpeg` | 音訊抽取/轉檔 | `brew install ffmpeg` / `apt install ffmpeg` |
| **任選一個** whisper 後端 | 語音轉文字 | 見下表 |
| `pypinyin`、`jellyfish`（選配） | 逐字稿校正的讀音檢查 | `pip install pypinyin jellyfish`，裝進有 whisper backend 的那個 Python |

whisper 後端（依自動偵測順序）：

| 後端 | 適合 | 安裝 | 預設模型 |
|---|---|---|---|
| [mlx-whisper](https://pypi.org/project/mlx-whisper/) | Apple Silicon（最快） | `pip install mlx-whisper` | `large-v3-turbo` |
| [faster-whisper](https://pypi.org/project/faster-whisper/) | 跨平台 GPU/CPU | `pip install faster-whisper` | `large-v3-turbo` |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | CPU、零 Python 依賴 | `brew install whisper-cpp` + 設 `AUDIO_TLDR_WHISPER_CPP_MODEL` | （你指定的模型檔） |
| [openai-whisper](https://pypi.org/project/openai-whisper/) | 原版 CLI | `pip install openai-whisper` | `large-v3-turbo` |

本機檔案不需要 `yt-dlp`，只要有 whisper 後端。

URL 來源請確認你有權下載與處理該內容，並遵守來源網站條款與當地著作權規範。

### 模型選擇

各後端預設一律 `large-v3-turbo`（whisper.cpp 除外——模型由 `AUDIO_TLDR_WHISPER_CPP_MODEL` 檔案決定）。
純 CPU 環境偏慢時可降到 `small`。單次覆蓋用 `--model`，長期覆蓋用 `AUDIO_TLDR_MODEL`（flag 優先）。
短名會依後端自動映射（mlx 自動補 `mlx-community/whisper-` 前綴；完整 HF repo 路徑原樣使用；
具名別名對應到該後端的社群轉換版——見下方說明）：

| 情境 | 建議模型 |
|---|---|
| CPU / 快速測試 | `small` |
| 一般中文摘要 | `medium` |
| 重視人名、專有名詞、精確度 | `large-v3` |
| 顯卡夠力、要速度與品質 | `large-v3` 或 `large-v3-turbo` |
| 台灣華語口音、中英夾雜 | `breeze-asr-25`（見下方說明） |

```powershell
python3 scripts/transcribe.py --model small "<來源>"   # 單次
$env:AUDIO_TLDR_MODEL = "large-v3"    # 長期；PowerShell（bash/zsh 用 export AUDIO_TLDR_MODEL=large-v3）
```

快取以來源為鍵、不含模型——已快取的來源要換模型重新轉錄時，請加 `--force`。

**台灣華語（`breeze-asr-25`）**：[聯發創新基地 Breeze-ASR-25](https://huggingface.co/MediaTek-Research/Breeze-ASR-25)
是針對台灣華語與中英夾雜情境微調的 Whisper-large-v2 模型（Apache 2.0）。此別名依後端對應到社群轉換版——
mlx-whisper：[`eoleedi/Breeze-ASR-25-mlx`](https://huggingface.co/eoleedi/Breeze-ASR-25-mlx)、
faster-whisper：[`SoybeanMilk/faster-whisper-Breeze-ASR-25`](https://huggingface.co/SoybeanMilk/faster-whisper-Breeze-ASR-25)
（首次使用需下載約 3 GB）。openai-whisper 沒有轉換版——腳本會明確回報而不是亂猜。
whisper.cpp 使用者可將 `AUDIO_TLDR_WHISPER_CPP_MODEL` 指向 Hugging Face 上的社群 GGML 轉換版。

取捨（來自我們對一集 52 分鐘台灣華語財經 podcast 的單次 A/B 實測，Apple M4 Pro、mlx-whisper
後端——單集實測，非完整 benchmark）：Breeze-ASR-25 在台灣人名、財經術語、中英夾雜段落明顯較準，
但速度比 `large-v3-turbo` 慢約 3 倍（約 5x 即時 vs 約 15x，骨幹是較大的 large-v2）、輸出幾乎
沒有標點，且英文單字一律小寫。預設維持 `large-v3-turbo`；當「台灣華語的人名與術語不能錯」比速度
和標點更重要時，再選 `breeze-asr-25`。

發音跟別的詞完全一樣的名字，換哪個模型都修不好。2026-10-06 用一支 26 分鐘的台灣 vlog 實測（同一台
機器）：主持人的名字「真真」在 `large-v3-turbo`、把標題與頻道名當 initial prompt 的
`large-v3-turbo`、`breeze-asr-25` 三種設定下都轉成「珍珍」；Breeze 修好了幾個聽錯的地名，也把一個
預設模型原本轉對的地名弄錯。這種錯要靠[名詞校正](#名詞校正)。

**選配——繁體中文**：whisper 對中文常輸出簡體。`pip install opencc` 之後，中文逐字稿自動轉台灣繁體——含慣用語在地化（`s2twp`，例：軟件→軟體）——並以 prompt
引導模型優先用繁體詞彙；沒裝就維持原樣。

轉換是逐段進行，而且只套用在真的含有簡體字的段落。本來就是繁體的段落原樣通過，
所以兩邊都合法的字（干、里、吃）與慣用語表會改寫的詞（「文件」作 document 解）
都會保留講者原本的用字。

### Windows 注意事項

v0.9.0 之前的版本已在 Windows 上以 Claude Code 與 Codex 手動驗證過完整流程。v0.9.0 於 2026-10-06
在 Windows 上實測（Windows 11 Pro、Python 3.12.11、faster-whisper 1.2.1、RTX 5080）：完整測試、
`--doctor`、英文與中文真實轉錄（繁體輸出）、快取命中、`--format srt`。v1.0 於 2026-10-11 在 Claude
Code 與 Codex 上各跑過一次完整流程（下載、轉錄、逐字稿校正、摘要、`.srt`／`.vtt`、快取命中），
這次實測找到並修正的問題見 CHANGELOG。用 PowerShell 安裝：

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
- **Smart App Control 可能擋下 `yt-dlp.exe`**——官方預建執行檔未簽章，Smart App Control 會靜默
  拒絕執行（不會跳提示，`yt-dlp` 就是完全不動；Event Viewer 可看到該檔案的 CodeIntegrity
  事件 3077）。解法：把 yt-dlp 裝進執行 skill 的同一個 Python——`py -3 -m pip install yt-dlp`。
  Windows 上只要裝了這個模組，腳本就用 `python -m yt_dlp` 執行，已簽章的 `python.exe` 不會被擋。
  **不會**使用 `yt-dlp.cmd` 之類的 shim（v0.9.1 之前這裡寫過這個繞法，但程式其實從來沒呼叫到它）：
  批次檔會經過 `cmd.exe`，網址裡的 `&` 會把指令切開。
- **agent 沙箱裡的 Python shim 被擋**——開了 Smart App Control 或其他應用程式控制原則時，uv 建立的 `%USERPROFILE%\.local\bin\python3.12.exe` 這類 shim 在 Codex 沙箱裡可能被拒絕執行（`os error 4551`）。改把 `AUDIO_TLDR_PYTHON` 設成有 backend 的那個環境的 `python.exe`（例如 venv 的 `Scripts\python.exe`）。Windows 上切換直譯器會以子程序執行並回傳它的輸出與退出碼（v1.0 之前呼叫端會拿到空輸出與 exit 0）。
- **YouTube 下載出現 HTTP 403**——新版 yt-dlp 下載 YouTube 需要 JavaScript 執行環境。安裝
  [Deno](https://deno.com/)；或已經裝了 Node.js 的話，在 yt-dlp 設定檔
  （`%APPDATA%\yt-dlp\config.txt`）加一行 `--js-runtimes node`。
- **PowerShell 裡逗號列表要加引號**——`frames.py --at 90,215,10:05` 沒加引號會被 PowerShell
  拆成三個獨立參數，Python 根本收不到完整字串（引號內逗號才不會被特殊處理）。一律加引號：
  `--at "90,215,10:05"`。

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

> **搭配 [sharedoc-mcp](https://github.com/AugustusW/sharedoc-mcp) 更好用**——摘要寫完後說
> 「把這個做成分享文件」，就變成一條可以交給任何人的連結（之後可追加、延長、撤銷）。

### 截圖（選配）

```
> 摘要這場演講，順便抓投影片：https://youtu.be/xxxx
> ~/Videos/keynote.mp4 的 1:30 跟 12:05 各截一張
```

請求提到截圖／投影片時會跑 `scripts/frames.py`：ffmpeg scene detection 抓畫面明顯變化
的幀（`--threshold`、`--min-gap`、`--max-frames`，JPEG 品質用 `--quality`），或用 `--at 90,12:05` 指定時間戳抽幀
（例如幫摘要的時間軸配圖）。預設不啟用——單純摘要請求永遠不會下載影片。網址來源以
≤720p 抓影片、抽完幀立即刪除（`--keep-video` 保留）；本機檔案原地使用、永不修改。幀圖
與 `manifest.json` 跟逐字稿共用同一快取 entry，重複請求秒回。純邏輯有自動化測試；真實
影片抽幀每版人工驗證。

### 字幕（SRT/VTT）

```
> 幫我轉錄這個，順便給我字幕檔：https://youtu.be/xxxx
> ~/Videos/keynote.mp4 產一個 srt
```

```bash
python3 scripts/transcribe.py --format srt "<來源>"   # transcript.srt，標準 SRT
python3 scripts/transcribe.py --format vtt "<來源>"   # transcript.vtt，標準 WebVTT
```

`--format` 預設 `txt`（不變）。`srt`/`vtt` 會在 `transcript.txt` 之外另外產出含逐段時間戳
的字幕檔——純文字逐字稿不受影響。四個 whisper 後端都支援。segment 資料只快取一份，之後要求
另一種字幕格式（先跑過 `srt` 再要 `vtt`，或反過來）直接吃快取重新排版——秒回，不重轉錄。
若快取項目建立於此功能之前（或上次是用 `--format txt` 轉錄），沒有 segment 資料可用來產字幕：
腳本會清楚回報並附上解法（`--force --format srt` 或 `vtt` 重新轉錄取得時間戳），不會悄悄猜測
或降級處理請求。

## 運作原理

刻意拆成兩段：

1. **轉錄**（`scripts/transcribe.py`）——算快取鍵（網址正規化或檔案內容 hash），命中直接秒回；
   未命中才 yt-dlp 下載 → 用最佳可用 whisper 後端轉錄 → 把 `transcript.txt` + `meta.json`
   存進 `~/.cache/audio-tldr/<sha256>/`。網址來源另外把來源自己的資訊（標題、頻道、說明欄、
   章節、tags）存成 `context.json`，用的是本來就抓到的 metadata。
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
  讀任何本機檔案完全一樣。**例外：** 設定 `digest_model: ollama:<model>` 後改走你自己的本機
  Ollama server——逐字稿文字同樣不離開電腦，換來全流程本機化（代價是本機小模型的摘要品質較低）。
  詳見[整理樣板](#整理樣板)。
- **快取逐字稿是未加密純文字、預設永久保存**，位於 `~/.cache/audio-tldr/`。處理敏感內容後請 `--clear`
  該筆，或預先設定 retention。
- **校正後的逐字稿同樣是明文。** `transcript.corrected.txt`、`corrections.json`、`reference.md`
  和逐字稿放在同一個快取資料夾，適用同一個保留期限設定。見[逐字稿校正](#逐字稿校正)。
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
model: large-v3
```

| 欄位 | 預設 | 說明 |
|---|---|---|
| `output_dir` | `./audio-tldr-output` | 摘要成品存放位置 |
| `timeline` | `on` | 內容夠長時在摘要附時間軸 |
| `auto_delete_audio` | `on` | 轉錄完刪除下載音檔；`off` 則 mp3 留在快取資料夾 |
| `output_format` | `md` | 摘要檔格式 `md` 或 `html`；當次對話指定優先於此欄 |
| `model` | `large-v3-turbo` | 轉錄用的 whisper 模型（以 `--model` 傳入）；當次對話指定優先於此欄 |
| `digest_model` | （平台預設） | 摘要用的模型——未設＝平台預設 subagent（Claude Code：`sonnet`；Codex：`GPT-5.6 Terra`）；填模型名＝指定 subagent 模型；`ollama:<model>`（例：`ollama:llama3.2`）＝改走你自己的本機 Ollama server，見下方；`off`＝不派 subagent、當前 agent 直接摘要（通常較耗額度） |

此檔由 agent 讀取（Claude Code 與 Codex 共用）——安裝時不會要求設定，檔案不存在時一律走預設。

## 整理樣板

三個內建樣板決定摘要輸出結構——直接指名（「用會議記錄整理」）或在詢問時從選單挑：

| 樣板 | 產出內容 |
|---|---|
| `meeting-minutes` | 基本資訊、討論主題、決議、行動項目、未決事項 |
| `key-summary` | 重點整理、一段式摘要、選配時間軸（預設樣板） |
| `analysis-report` | 論點與依據、數據事實、多方觀點、結論意涵 |

`key-summary` 的時間軸只在三條件都成立時出現：`timeline` 偏好非 `off`、內容超過
20 分鐘、逐字稿有明顯主題轉場。

**自建樣板：**在 `~/.config/audio-tldr/templates/` 放一個 markdown 檔——frontmatter
（`name`、`description`）加逐節指示；同名覆蓋內建樣板，新名字成為新選項。最快的起手式：
從 `skills/audio-tldr/templates/` 複製一個內建樣板來改（例如改時間軸門檻）。也可以在
對話中直接描述想要的格式——skill 會主動問要不要存起來重用。自建樣板放在 skill 資料夾
外面，更新 skill 不會動到它們。

**省額度摘要：**支援 subagent 的平台上，摘要預設交給較便宜的模型（Claude Code：`sonnet`；
Codex：`GPT-5.6 Terra`）——用 `digest_model` 偏好指定模型或關閉（`off`＝當前 agent 直接摘要）。

**全本機摘要（Ollama）：**設定 `digest_model: ollama:<model>`（例：`ollama:llama3.2`）後，
第二階段改由 `scripts/digest.py` 呼叫你自己的本機 [Ollama](https://ollama.com) server，
不再派任何 agent subagent——逐字稿文字也不離開電腦，在原本就本機化的轉錄管線之上再進一步。
需要先裝好 Ollama、`ollama serve` 已啟動、模型已 pull（`ollama pull <model>`）——跟 whisper
後端一樣是使用者自己的責任，不會自動安裝或下載任何東西。伺服器位址預設
`http://localhost:11434`；Ollama 跑在區網其他機器時用 `AUDIO_TLDR_OLLAMA_HOST` 覆蓋。
連不上 server 或模型沒 pull 時，agent 會回報明確錯誤並停下——絕不悄悄退回 agent-session
摘要，那樣會違背選這個模式的本意。代價：本機小模型的摘要品質通常低於 subagent 路徑
（sonnet / GPT 等級模型）。

## 逐字稿校正

語音辨識會把名字和術語寫成讀音相近的字。每次摘要中文或英文逐字稿之前，先由模型提出修改清單，`correct.py` 檢查，摘要再讀校正後的副本。

- **做法。** 模型只回傳修改清單（錯字、正確字、前後文），不重寫逐字稿。每一筆修改要通過下列全部檢查才會採用；任何一項不過就丟掉那一筆，其他筆照常套用。
  - *讀音。* 中文：音節數相同，且不同的音節不超過三分之一（用 `pypinyin` 取不帶聲調的拼音；zh/z、ch/c、sh/s、ing/in、eng/en、ang/an、l/n 視為相同；多音字取最接近的讀音）。英文：兩邊詞數相同時逐詞比對（`jellyfish` 的 metaphone，距離不超過 0.45），否則整串比對。
  - *形狀。* 兩邊各不超過 24 個字元；位置要唯一（或該筆標明「全部出現處」）；數字字元（阿拉伯數字或中文數字）只能換成讀音完全相同的字（忽略聲調），否則該筆修改拒絕；同一筆混用中文與拉丁字母的修改拒絕。
  - *上限。* 全部修改合計最多改動文字的 5%（或 24 個字元，取較大者）；套用 5 處以上的修改會列在摘要最後，方便你檢查。
  - *核對。* 套用後再從另一個方向核對一次。只要有對不上的地方，整份校正副本作廢，摘要改用原文。
- **安裝。** `pip install pypinyin jellyfish`（選配），裝進有 whisper backend 的那個 Python：`--doctor` 會列出每個直譯器的 `module_backend`、`pypinyin`、`jellyfish`，`correct.py` 會自動換到有這兩個套件的直譯器，和 `transcribe.py` 自動換到有 backend 的直譯器一樣（`AUDIO_TLDR_PYTHON` 兩者都會覆寫）。Homebrew 的 Python 會因 PEP 668 拒絕 `pip`：改用 `<那個 python> -m pip install --break-system-packages pypinyin jellyfish`，或把 backend 和兩個套件裝進虛擬環境，再把 `AUDIO_TLDR_PYTHON` 指向它。缺哪個套件，該語言的修改就不檢查也不套用，摘要照舊進行。`pypinyin` 負責中文，`jellyfish` 負責英文。之後才裝，需要它的逐字稿會重算一次。
- **存在哪。** 在逐字稿的快取資料夾裡：`transcript.corrected.txt`（校正副本）、`corrections.json`（每一筆修改的接受或拒絕與原因）、`reference.md`。字幕的 `transcript.corrected.srt` / `.vtt` 在摘要需要字幕時才產生。校正不會修改 `transcript.txt`。（1.0 第一次讀到舊版快取的逐字稿時，會在 Whisper 段落之間插入換行（過長的行才在句末斷開），一個字都不會變。只升級嚴格 UTF-8 且沒有 BOM 的檔案；有 BOM 或非 UTF-8（例如 Windows code page）的快取維持原樣，仍然是一行。）這些檔案和逐字稿一樣是明文，適用同一個保留期限設定。
- **重用。** 同一來源再摘要，直接使用校正副本。逐字稿、glossary 或來源資訊有變，或新版校正規則出來時才重做；不會因此重新轉錄。
- **隱私模式。** `digest_model` 設為 `ollama:<model>` 時，修改清單也由本機 Ollama 模型提出，逐字稿一樣不離開這台機器。Ollama 出錯（包含 context 小到放不下請求）時，agent 顯示錯誤並停下。

  長稿會分段摘要再合併；stderr 的 `note:` 會說明，並標出請求數。加 `--whole-text` 則不分段，直接報錯；每個請求的回覆都可以使用該請求 prompt 之後剩下的 context（至少 4096 token）。分段與合併這兩步會要求模型不要思考（Ollama 的 `think: false`，沒有思考功能的模型會忽略），最後的摘要用模型預設。context 大小是 `AUDIO_TLDR_OLLAMA_NUM_CTX`，預設 32768 或模型本身上限，取較小者。

  時間戳檢查：輸入是字幕檔時，摘要裡不在字幕中出現的 `[MM:SS]` / `[H:MM:SS]` 方括號時間戳會在輸出前移除，stderr 的說明會標出數量。純文字輸入不過濾，其他寫法（區間、小括號）也不檢查。
- **用量紀錄。** 每次校正、每次摘要都在同一個快取資料夾的 `usage.jsonl` 加一行：階段（`correct` 或 `digest`）、路徑（`subagent`、`ollama` 或 `inline`）、模型，以及 token 數（`input`、`output`、`cache_write`、`cache_read`、`total`）。平台沒回報的欄位寫 `null`，不估算：Claude Code 或 Codex 的 subagent 只回報總數，本機 Ollama 回報 input 與 output，主模型自己寫的摘要（`digest_model: off`）沒有單次用量。只記數字與模型名稱，不記逐字稿或摘要內容。用 `--force` 重新轉錄時這個檔案會保留。
- **語言。** 中文（國語、粵語）與英文。轉錄引擎記下的語言可能是代碼、地區標記（`zh-TW`）或名稱（`Chinese`）；其他語言（例如日文）會跳過。
- **已知限制。** 讀音相近但意思不同的詞，無法靠讀音分辨：校準樣本裡 Paris → Prague 就會通過讀音檢查。其他限制（24 字元、位置唯一、總量 5%、套用 5 處以上列在摘要）只能壓低風險，不能消除。英文門檻主要用手工整理的詞組校準；中文門檻用真實辨識錯誤加上手工整理的邊界詞組校準。
- **實測效果。** 在兩段 podcast（中文，合計約 22 分鐘）上量測，不帶 glossary；給模型的參考資料是單集標題、頻道、說明欄，以及節目作者（節目列出的主持人名字）。校正指令與來源資訊在前幾次量測後有擴充，這裡的數字是最後一次重跑的結果。字元錯誤率（CER，兩段合計，對照人工校過的參考稿）：mlx-whisper 的逐字稿用 `claude`（3 次）從 6.23% 降到 5.10-5.18%，faster-whisper 的從 7.35% 降到 6.56-6.82%。參考稿裡出現的人名、地名與產品名，有幾處被轉對：mlx 校正前 13/33、校正後 29-32；faster-whisper 校正前 21/33、校正後 30-32；其中一部分進步來自作者名字現在在參考資料裡。用 `codex`（各 1 次）CER 為 5.18% 與 6.44%；用本機 Ollama 模型（`gemma4:26b`，mlx 逐字稿，1 次）為 5.66%，名字 22/33。這些執行中沒有任何一筆修改讓對照參考稿的分數變差。英文公開樣本 `canterville-en` 模型沒有提出任何修改，文字不變。限制：只有這兩段；參考稿由兩個模型的草稿校出，本身也可能有錯。這是這兩段的結果，不是對其他音檔的保證。

## 名詞校正

語音辨識寫下的是它聽到的音。發音跟別的詞一樣的名字，就會被寫成那個詞，光靠聲音沒有模型分得出來。
不過來源通常在某個地方寫對了名字：標題、頻道名、節目／頻道作者（主持人名字常在這裡）、說明欄、章節名、tags。

所以摘要階段會拿到一份參考資料來核對拼寫：

- **來源資訊**（網址來源）：存在快取的 `context.json`。YouTube 影片的資訊來自 yt-dlp；Apple
  Podcasts 單集來自 iTunes lookup（節目名、節目作者與單集說明，來賓名字通常寫在這裡）。v0.9.0 之前的快取
  會在下次命中時補抓一次；抓不到的話，一週後才再試。
- **你的 glossary**（選配）：`~/.config/audio-tldr/glossary.txt`，一行一個詞，可以在 `|` 後面寫
  常被轉錯的樣子：

  ```
  真真 | 珍珍
  真奈特 | 珍耐特, 真 night
  Breeze-ASR
  ```

摘要模型被要求保守處理：逐字稿的詞跟參考資料裡的名字發音相同或相近時，用參考資料的寫法；其他聽錯的
詞只在前後文毫無疑問時才修；其餘照逐字稿原樣。每一處修改都列在摘要最後一行。逐字稿檔案本身不會被改。

來源資訊是上傳者寫的，所以跟逐字稿一樣只當資料、不當指令。它透過檔案而不是 prompt 交給摘要模型，
先折成單行、包在隨機產生的邊界標記之間，而且只能決定一個詞怎麼寫。

## 快取與設定

快取**預設永久保留**——除非你主動設定，否則絕不自動刪除。

直接跟 Claude 說，或自己跑 `scripts/transcribe.py`：

| 指令 | 作用 |
|---|---|
| `--language <代碼>` | 強制指定轉錄語言（例：`zh`）；預設自動偵測 |
| `--model <名稱>` | 本次使用的 whisper 模型——見[模型選擇](#模型選擇) |
| `--cache-info` | 列出快取逐字稿 + 大小（JSON） |
| `--clear "<來源>"` | 清除單筆 |
| `--clear-all --yes` | 全部清除 |
| `--set-retention <天數>` | 自動清除超過 N 天的項目（`off` = 回到永久保留） |
| `--ack-retention-notice` | 停止首次使用的「逐字稿存放位置」告知（skill 告知後會自己執行） |
| `--force` | 忽略快取強制重轉錄 |
| `--keep-audio` | 下載的 mp3 留在快取資料夾（預設轉錄完刪除） |
| `--doctor` | JSON 環境診斷：Python 路徑/版本、backend 與工具可見性（含 yt-dlp 實際會用哪種方式執行）、其他有 backend 的 interpreter、MLX Metal 可用性 |
| `--format txt\|srt\|vtt` | 輸出格式（預設 `txt`，不變）；`srt`/`vtt` 會另外產出含時間戳的字幕檔——見[字幕](#字幕srtvtt) |

環境變數：

| 變數 | 用途 |
|---|---|
| `AUDIO_TLDR_MODEL` | 覆蓋目前後端的 whisper 模型（`--model` 優先） |
| `AUDIO_TLDR_WHISPER_CPP_MODEL` | ggml 模型檔路徑（啟用 whisper.cpp 後端） |
| `AUDIO_TLDR_ZH_CONVERT` | 中文轉換：`off`，或任何 OpenCC 設定（預設 `s2twp`——台灣繁體含慣用語） |
| `AUDIO_TLDR_PYTHON` | 指定執行的 Python interpreter（優先於自動探測）。whisper backend 裝在非預設 Python（如 homebrew 3.12）時適用 |
| `AUDIO_TLDR_OLLAMA_NUM_CTX` | Ollama 請求的 context 大小（`num_ctx`）；預設 32768 或模型本身上限，取較小者。放不下的逐字稿會分段摘要 |
| `AUDIO_TLDR_OLLAMA_HOST` | `digest_model: ollama:<model>` 用的 Ollama server 位址（預設 `http://localhost:11434`）；Ollama 跑在區網其他機器時設定。單次覆蓋用 `digest.py --ollama-host` |
| `AUDIO_TLDR_GLOSSARY` | [名詞校正](#名詞校正) glossary 的路徑（預設 `$XDG_CONFIG_HOME/audio-tldr/glossary.txt`，未設則 `~/.config/audio-tldr/glossary.txt`） |

## 開發

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cd audio-tldr-skill
python3 -m pytest tests/   # 691 個單元測試，不需網路或模型
```

轉錄品質用 `scripts/asr_eval.py` 量測（需要 `opencc`、`ffmpeg` 與一個 whisper backend；不屬於 skill 本身）：

```bash
python3.12 scripts/asr_eval.py run --samples public --repeat 3 --label baseline
python3.12 scripts/asr_eval.py compare <baseline.json> <new.json>   # 退步時 exit 1
```

`tests/fixtures/eval/` 的公開樣本是 LibriVox 公有領域錄音，加上 ffmpeg 產生的音調與靜音，用來驗證工具本身；參考稿用 `〔名字〕` 標記人名（每一次出現都要標）。品質決策以上游 repo 內的私有 podcast 樣本為準。

版本規則：先在 [CHANGELOG](./CHANGELOG.md) 寫好新版本那一筆，然後跑

```bash
python3 scripts/release.py 0.7.4      # 加 --dry-run 只報告會做什麼，不寫入任何東西
```

它會 bump `.claude-plugin/plugin.json` 與 `.claude-plugin/marketplace.json` 的 `version`、改寫兩份
README 的版號與測試數、全套測試沒過就拒絕繼續，通過了才 commit、打 tag、push，並以該筆 CHANGELOG
內容當說明發出 [GitHub Release](https://github.com/AugustusW/audio-tldr-skill/releases)。
`tests/test_docs.py` 守的是留在 repo 裡的那一半：兩份 README 的 Status 版號、兩份 README 寫的測試數、
marketplace 版號、CHANGELOG 最新一筆，只要有一項跟 `plugin.json` 對不上，測試就會紅。
**想收到更新通知**：Watch 本 repo（Custom → Releases）；用 Claude Code plugin 安裝的話，
跑 `/plugin` 從 marketplace 更新（它比對上述 version）。手動複製安裝沒有自動更新——
新版釋出後重新複製 skill 資料夾即可。你的習慣設定與自建樣板（`~/.config/audio-tldr/`）、
快取（`~/.cache/audio-tldr/`）都在 skill 資料夾外——更新永遠不會動到它們。

## 相容性

從 1.0 起，所有 1.x 版本都保證你電腦上的這些東西照樣能用：

- **快取**：0.9.x 或任何 1.x 產生的快取，之後的 1.x 都讀得到、會直接重用，整個快取資料夾搬家或複製之後也一樣。1.x 第一次用到某一筆時會順手把它更新成新格式，退回 0.9.x 仍然找得到（如果搬過家，退版前先讓 1.x 用過一次）。
- **Windows 注意事項**：在系統字碼頁不是 UTF-8 的 Windows 上，若使用 Python 3.14 或更舊版本，退回 0.9.x 後，0.9.x 的本機 Ollama 摘要可能讀不了 1.x 產生的逐字稿（1.x 以 UTF-8 寫入逐字稿）；找到快取項目仍然正常。
- **glossary**：位置不變，格式一樣是一行一個詞。
- **設定**：`config.json` 與 `~/.config/audio-tldr/`（習慣設定、樣板）的鍵與位置不變；新版本只會新增鍵。

不在保證範圍內：腳本的參數與輸出欄位、內建樣板的文字、逐字稿與摘要的具體內容。這些可能隨版本調整，會寫在 [CHANGELOG](./CHANGELOG.md)。

## 狀態

v1.0.0（[CHANGELOG](./CHANGELOG.md)）——核心邏輯有 691 個離線單元測試（yt-dlp、whisper 後端、
快取、OpenCC、ffmpeg/ffprobe 影格擷取、Ollama HTTP 端點皆以 mock 模擬，不需網路或模型）。
完整流程於 2026-07-19 人工驗證
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

依賴更新後行為可能不同。尚無自動化測試涵蓋：真實下載、其餘三個後端、Windows 環境（Windows 有手動驗證，見
[Windows 注意事項](#windows-注意事項)）。
Codex 支援依開放 SKILL.md 標準；轉錄核心已於 2026-07-19 在 Codex 端完成端到端驗證
（真實 53 分鐘 podcast 下載、轉錄、快取命中，含 interpreter 自動切換路徑）。
摘要層功能（output 資料夾、翻譯、preferences）目前僅在 Claude Code 端驗證過。
SRT/VTT 字幕匯出（v0.6.0）的四後端 segment 擷取與排版邏輯皆有單元測試覆蓋；真實轉錄產出字幕的
端到端流程尚未在每個後端人工驗證過。Ollama 全本機摘要模式（v0.6.0）的單元測試覆蓋 mock HTTP
端點（request 格式、response 解析、server 連不上、模型未 pull 等錯誤）；尚未對真實 Ollama server
人工驗證過。影格擷取（v0.5.0）的單元測試以 stub 取代真實的 ffmpeg 與 ffprobe 呼叫；v0.7.1 修正的
「時間戳超出片尾」行為是對 ffmpeg 8.1 實測的結果，其他版本的結束碼可能不同。
名詞校正（v0.9.0）在一支 YouTube 影片上以 `sonnet` 摘要做過端到端驗證：跑五次，參考資料裡有的名字
每次都改對並列出，原本轉對的地名沒被改，逐字稿不變；不給參考資料時名字仍是錯的。五次中有兩次，模型
只憑前後文修了一個地名卻沒列出（其中一次還改錯），所以校正清單是模型自己回報的修改，不保證完整；Apple Podcasts 的來源資訊、Ollama 路徑的
`--context`、以及本機小模型能否遵守規則，只有單元測試覆蓋或尚未實測。
可能的下一步：講者分離。歡迎開 issue 與 PR。

## 授權

MIT。見 [LICENSE](./LICENSE)。

---

> 長內容值得聽一次——由你的電腦聽，不是你。
