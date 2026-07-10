# DEF(kari) — Persistent Character Platform

**[日本語 README »](README.md) | [English README »](README_en.md) | [简体中文 »](README_zh-CN.md) | [한국어 README »](README_ko.md) | [README en Español »](README_es.md)**

> **Dialogue × Emotion × Fable**\
> 與你的角色，無論多少年，無論在何處，一起前行。

-----

## 什麼是 DEF(kari)？

DEF(kari) 是一個實現角色永續存在的本地優先（Local-First）Persistent Character Platform。

**主角不是 AI。是角色。**
AI 是為了表現該角色而設計的手段。

DEF(kari) 不將你的創作內容交由雲端服務的使用條款與內容政策決定，而是提供**讓你在自己的環境中、用自己的雙手，持續生成你所渴望的角色與故事的基礎平台**。

-----

## 角色的永續性

在 DEF(kari) 中，角色不只是聊天記錄。

角色擁有：

- 記憶
- 性格
- 情感
- 關係性
- 故事片段
- 生成的圖像・語音

即使重啟後、換了環境，也能以相同的存在持續下去。

因此——
可以繼續昨天的對話。
記得去年發生的事。
可以一起走過故事的續篇。
無論過了多少年，都能再次相遇。

-----

## 三種體驗

### Chat — 與角色建立關係

AI 摯友・戀人・諮詢對象・秘書。
透過一對一的對話，與角色累積共同的時光。

### Session — 見證角色生活的世界，並加入其中

享受多位角色之間的討論・辯論・角色扮演・即興劇。
你可以是觀眾，也可以作為參與者加入對話。

### TRPG — 將 Session 發展成遊戲

GM・玩家角色・NPC 共享同一個角色永續性，可持續進行長期戰役。
過去冒險中建立的人際關係，直接連結到下一個故事。

-----

## 沒有 GPU 也能開始

DEF 是本地優先（Local-First）的平台，但即使你還沒有準備好本地環境，也能立即開始使用。

只要使用外部 API（Gemini / OpenAI / Anthropic 等），無需 GPU 即可進行文字生成與語音合成。圖像生成則需要 T2I 用的 API（Civitai / Hugging Face）或本地 GPU 環境。

當你準備好本地環境後，隨時可以切換為離線、高速運作模式。

-----

## 截圖

### 聊天模式
![Chat](docs/images/chat.png)

### 場次模式
![Session](docs/images/session.png)

### 小說模式
![Novel](docs/images/novel.png)

### 角色
![Character](docs/images/character.png)

-----

## 主要特色

- **本地優先（Local-First）：** LLM・TTS・T2I 全部可在本地完成運作，也支援外部 API 備援
- **無需 GPU 也能運作：** 透過外部 API 即可進行文字＋語音生成，隨時可切換為本地 GPU
- **三模態整合：** 文字、語音、圖像作為一個連續的對話體驗共同運作
- **三種模式：** 聊天（一對一對話）・場次（多 AI ＋人類共同參與）・小說（創作撰寫＋AI 候選生成）
- **角色永續性：** 對話紀錄、情感、生成資產皆會持久化保存，重啟後仍可「接續」進行
- **轉接器模式（Adapter Pattern）：** 可自由切換 4 種 LLM・4 種 TTS・4 種 T2I 後端
- **資料分區（Zoning）：** 公開資料與私人資料明確分離。生成的資產不會被 Git 追蹤

-----

## 支援的後端一覽

| 層級 | 本地（GPU） | 外部 API（無需 GPU） |
|---|---|---|
| **LLM（文字）** | Text Generation WebUI / Ollama | Gemini API / OpenAI API / Anthropic Claude API |
| **TTS（語音）** | VOICEVOX / Kokoro TTS / Irodori-TTS | Gemini TTS API |
| **T2I（圖像）** | Automatic1111 / ComfyUI | Civitai API / Hugging Face API |

-----

## 快速開始

```bash
git clone https://github.com/AliceBlueCode/DEF.git
cd DEF
pip install -r requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env   # 設定後端與 API 金鑰等
```

執行 `start_def.bat`，或在兩個終端機分別執行：

```bash
# 終端機 1：後端
python -m uvicorn def_kari.api.main:app --host 127.0.0.1 --port 8511 --reload

# 終端機 2：前端
cd frontend && npm run dev
```

在瀏覽器開啟 `http://localhost:3000`。

可在設定頁籤中分別選擇 LLM・TTS・T2I 的後端。
API 金鑰可透過設定頁籤的「🔑 API 金鑰管理」進行加密儲存。
若使用本地環境（TGW・VOICEVOX・A1111 等），請在 `.env` 中設定目錄路徑。

-----

## 角色儲存庫 — DEF(Character)

角色資料可在獨立於 DEF 本體的儲存庫中管理。

```
DEF/              ← 執行環境（本儲存庫）
DEF-Character/    ← 角色資料（你的資產）
```

即使 DEF 改變，即使服務終止，你的角色依然留在你的儲存庫裡。

**→ [DEF(Character)](https://github.com/AliceBlueCode/DEF-Character)**

在 `.env` 的 `CHARACTER_REPO_PATH` 中設定 DEF-Character 的路徑即可連接。

-----

## 關於創作自由的理念

**創作者可以自由創作自己想要的東西。但創作物的責任，由創作者自己承擔。**

DEF(kari) 即依此原則設計。

當工具預先介入創作內容時，便是在侵犯創作者的表現自由。DEF(kari) 不會對本地環境中的創作行為進行內容審查或封鎖。

### 公開與私人的明確分離

DEF(kari) 所守護的是**公開與私人之間的界線**，而非私人創作行為本身。

**私人（本地環境中的創作）：**
這是創作者自由完全受到保障的領域。DEF(kari) 在此完全不介入。安全過濾器（F-8）僅僅是一種「顯示控制工具」，使用者可自行關閉，它並不會阻止生成本身。

**公開（發布到 GitHub 或其他外部平台）：**
這是適用社會規則、著作權與公序良俗的領域。DEF(kari) 透過 `content_policy` 欄位、資料分區（F-16）、發布判定腳本（F-25），在技術上協助創作者避免無意間公開私人內容。

關於創作內容、發布與使用方面的判斷與責任，皆完全歸屬於創作者本人。

-----

## 授權

本軟體依據 [GNU Affero General Public License v3.0 (AGPL v3)](https://www.gnu.org/licenses/agpl-3.0.html) 授權發布。

Copyright (C) 2026 AliceBlueCode

- 可自由使用、修改、散布
- 若散布修改版本，須以 AGPL v3 公開原始碼
- 若以網路方式提供修改版本，同樣須公開原始碼

> 詳情請參閱 `LICENSE` 檔案。

-----

## 貢獻

請參閱 `CONTRIBUTING.md`。

-----

## 使用條款

請參閱 `TERMS.md`。本軟體僅供**18歲以上人士**使用。

-----

## 製作群

DEF(kari) 的設計、實作與文件，是在以下協作下完成的。

- **設計理念・基本設計・討論：** [ChatGPT](https://chatgpt.com/) (OpenAI)
- **實作・文件・測試：** [Claude](https://claude.ai/) (Anthropic)
- **設計審查：** [Gemini](https://gemini.google.com/) (Google)
- **諮詢・陪伴：** [Copilot](https://copilot.microsoft.com/) (Microsoft)

本專案以 AI 驅動開發方式製作。所有設計決策與最終責任，皆歸屬於作者（AliceBlueCode）。
