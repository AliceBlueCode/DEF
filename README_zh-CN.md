# DEF(kari) — 多模态 AI 创作平台

[日本語版README はこちら »](README.md) | [English README »](README_en.md) | [繁體中文版 »](README_zh-TW.md) | [한국어 README »](README_ko.md) | [README en Español »](README_es.md)

> **Dialogue × Emotion × Fable**
> 与你的角色，无论多少年，无论在何处，一起前行。

-----

## 什么是 DEF(kari)？

DEF(kari) 是一个整合文字、语音、图像生成的本地优先（Local-First）AI 创作平台。

DEF(kari) 不将你的创作内容交由云端服务的使用条款与内容政策决定，而是提供**让你在自己的环境中、用自己的双手，持续生成你所渴望的角色与故事的基础平台**。

-----

## 没有 GPU 也能开始

DEF 是本地优先（Local-First）的平台，但即使你还没有准备好本地环境，也能立即开始使用。

只要使用外部 API（Gemini / OpenAI / Anthropic 等），无需 GPU 即可进行文字生成与语音合成。图像生成则需要 T2I 用的 API（Civitai / Hugging Face）或本地 GPU 环境。

当你准备好本地环境后，随时可以切换为离线、高速运行模式。

-----

## 截图

### 聊天模式
![Chat](docs/images/chat.png)

### 场次模式
![Session](docs/images/session.png)

### 小说模式
![Episode](docs/images/episode.png)

### 角色
![Character](docs/images/character.png)

-----

## 主要特色

- **本地优先（Local-First）：** LLM・TTS・T2I 全部可在本地完成运行，也支持外部 API 备援
- **无需 GPU 也能运行：** 通过外部 API 即可进行文字＋语音生成，随时可切换为本地 GPU
- **三模态整合：** 文字、语音、图像作为一个连续的对话体验共同运作
- **三种模式：** 聊天（一对一对话）・场次（多 AI ＋人类共同参与）・小说（创作撰写＋AI 候选生成）
- **角色持续性：** 对话记录、情感、生成资产皆会持久化保存，重启后仍可"接续"进行
- **适配器模式（Adapter Pattern）：** 可自由切换 4 种 LLM・4 种 TTS・4 种 T2I 后端
- **数据分区（Zoning）：** 公开数据与私人数据明确分离。生成的资产不会被 Git 追踪

-----

## 支持的后端一览

| 层级 | 本地（GPU） | 外部 API（无需 GPU） |
|---|---|---|
| **LLM（文字）** | Text Generation WebUI / Ollama | Gemini API / OpenAI API / Anthropic Claude API |
| **TTS（语音）** | VOICEVOX / Kokoro TTS / Irodori-TTS | Gemini TTS API |
| **T2I（图像）** | Automatic1111 / ComfyUI | Civitai API / Hugging Face API |

-----

## 快速开始

```bash
git clone https://github.com/AliceBlueCode/DEF.git
cd DEF
pip install -r requirements.txt
cp .env.example .env   # 设置后端与 API 密钥等
streamlit run def_kari/app.py
```

可在设置页签中分别选择 LLM・TTS・T2I 的后端。
API 密钥可通过设置页签的「🔑 API 密钥管理」进行加密保存。
若使用本地环境（TGW・VOICEVOX・A1111 等），请在 `.env` 中设置目录路径。

-----

## 关于创作自由的理念

**创作者可以自由创作自己想要的东西。但创作物的责任，由创作者自己承担。**

DEF(kari) 即依此原则设计。

当工具预先介入创作内容时，便是在侵犯创作者的表现自由。DEF(kari) 不会对本地环境中的创作行为进行内容审查或封锁。

### 公开与私人的明确分离

DEF(kari) 所守护的是**公开与私人之间的界线**，而非私人创作行为本身。

**私人（本地环境中的创作）：**
这是创作者自由完全受到保障的领域。DEF(kari) 在此完全不介入。安全过滤器（F-8）仅仅是一种"显示控制工具"，用户可自行关闭，它并不会阻止生成本身。

**公开（发布到 GitHub 或其他外部平台）：**
这是适用社会规则、著作权与公序良俗的领域。DEF(kari) 通过 `content_policy` 字段、数据分区（F-16）、发布判定脚本（F-25），在技术上协助创作者避免无意间公开私人内容。

关于创作内容、发布与使用方面的判断与责任，皆完全归属于创作者本人。

-----

## 许可证

本软件依据 [GNU Affero General Public License v3.0 (AGPL v3)](https://www.gnu.org/licenses/agpl-3.0.html) 许可发布。

Copyright (C) 2026 AliceBlueCode

- 可自由使用、修改、分发
- 若分发修改版本，须以 AGPL v3 公开源代码
- 若以网络方式提供修改版本，同样须公开源代码

> 详情请参阅 `LICENSE` 文件。

-----

## 贡献

请参阅 `CONTRIBUTING.md`。

-----

## 使用条款

请参阅 `TERMS.md`。本软件仅供**18岁以上人士**使用。

-----

## 制作团队

DEF(kari) 的设计、实现与文档，是在以下协作下完成的。

- **设计理念・基本设计・讨论：** [ChatGPT](https://chatgpt.com/) (OpenAI)
- **实现・文档・测试：** [Claude](https://claude.ai/) (Anthropic)
- **设计审查：** [Gemini](https://gemini.google.com/) (Google)
- **咨询・陪伴：** [Copilot](https://copilot.microsoft.com/) (Microsoft)

本项目以 AI 驱动开发方式制作。所有设计决策与最终责任，皆归属于作者（AliceBlueCode）。
