# DEF(kari) — Persistent Character Platform

**[日本語 README »](README.md) | [English README »](README_en.md) | [繁體中文 »](README_zh-TW.md) | [简体中文 »](README_zh-CN.md) | [README en Español »](README_es.md)**

> **Dialogue × Emotion × Fable**\
> 당신의 캐릭터와, 몇 년이 지나도, 어디서든, 함께.

-----

## DEF(kari)란?

DEF(kari)는 캐릭터의 영속적인 존재를 실현하는 로컬 퍼스트(Local-First) Persistent Character Platform입니다.

**주인공은 AI가 아닙니다. 캐릭터입니다.**
AI는 그 캐릭터를 표현하기 위한 수단으로 설계되었습니다.

클라우드 서비스의 이용약관이나 콘텐츠 정책에 창작 내용을 맡기는 대신, **자신의 환경에서, 자신의 손으로, 원하는 캐릭터와 이야기를 계속 생성할 수 있는 기반**을 제공합니다.

-----

## 캐릭터의 영속성

DEF(kari)에서 캐릭터는 단순한 채팅 기록이 아닙니다.

캐릭터는,

- 기억
- 성격
- 감정
- 관계성
- 에피소드
- 생성된 이미지・음성

을 보존하며, 재시작 후에도, 환경이 바뀌어도, 같은 존재로 계속됩니다.

그렇기 때문에,
어제의 이야기를 이어갈 수 있습니다.
작년의 일을 기억하고 있습니다.
이야기의 다음 장을 함께 걸을 수 있습니다.
그리고 몇 년이 지나도 다시 만날 수 있습니다.

-----

## 세 가지 체험

### Chat — 캐릭터와 관계를 쌓다

AI 친구・연인・상담 상대・비서.
일대일 대화를 통해 캐릭터와의 시간을 쌓아갑니다.

### Session — 캐릭터들이 살아가는 세계를 지켜보고, 참여하다

여러 캐릭터들의 토론・논의・롤플레이・즉흥극을 즐깁니다.
당신은 관객이 될 수도, 참가자로 대화에 참여할 수도 있습니다.

### Novel — 캐릭터와 함께 이야기를 쓰다

지문・대화・삽화를 결합한 소설 집필을 지원합니다.
AI 후보 생성・TTS 낭독・T2I 삽화가 연동되어, 캐릭터가 이야기의 주인공으로 계속 존재합니다.

-----

## GPU가 없어도 시작할 수 있습니다

DEF는 로컬 퍼스트이지만, 로컬 환경이 갖춰져 있지 않아도 바로 시작할 수 있습니다.

외부 API(Gemini / OpenAI / Anthropic 등)를 이용하면 GPU 없이도 텍스트 생성과 음성 합성이 동작합니다. 이미지 생성에는 T2I용 API(Civitai / Hugging Face) 또는 로컬 GPU 환경이 필요합니다.

로컬 환경이 갖춰지면 언제든지 오프라인・고속 동작으로 전환할 수 있습니다.

-----

## 스크린샷

### 채팅 모드
![Chat](docs/images/chat.png)

### 세션 모드
![Session](docs/images/session.png)

### 노벨 모드
![Novel](docs/images/novel.png)

### 캐릭터
![Character](docs/images/character.png)

-----

## 주요 특징

- **로컬 퍼스트(Local-First):** LLM・TTS・T2I 모두 로컬에서 완결. 외부 API로의 폴백도 지원
- **GPU 없이도 동작:** 외부 API를 통해 텍스트＋음성 동작. 로컬 GPU로의 전환은 언제든지 가능
- **3가지 모달리티 통합:** 텍스트・음성・이미지가 하나의 대화로 연속해서 동작
- **3가지 모드:** 채팅(1대1 대화)・세션(다수 AI＋인간의 테이블)・노벨(소설 집필＋AI 후보 생성)
- **캐릭터 영속성:** 대화 이력・감정・생성 자산이 영속화되어, 재시작 후에도 "이어서" 재개 가능
- **어댑터 패턴(Adapter Pattern):** LLM×5・TTS×5・T2I×4의 백엔드를 자유롭게 교체 가능
- **조닝(Zoning):** 공개 데이터와 비공개 데이터의 명확한 분리. 생성 자산은 Git 관리 대상 외

-----

## 지원 백엔드 목록

| 레이어 | 로컬(GPU) | 외부 API(GPU 불필요) |
|---|---|---|
| **LLM(텍스트)** | Text Generation WebUI / Ollama | Gemini API / OpenAI API / Anthropic Claude API |
| **TTS(음성)** | VOICEVOX / Kokoro TTS / Irodori-TTS | Gemini TTS API / OpenAI TTS API |
| **T2I(이미지)** | Automatic1111 / ComfyUI | Civitai API / Hugging Face API |

-----

## 빠른 시작

```bash
git clone https://github.com/AliceBlueCode/DEF.git
cd DEF
pip install -r requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env   # 백엔드 설정・API 키 등을 입력
```

`start_def.bat`을 더블클릭하거나, 두 개의 터미널에서 각각 실행하세요:

```bash
# 터미널 1: 백엔드
python -m uvicorn def_kari.api.main:app --host 127.0.0.1 --port 8511 --reload

# 터미널 2: 프론트엔드
cd frontend && npm run dev
```

브라우저에서 `http://localhost:3000`을 여세요.

설정 탭에서 LLM・TTS・T2I의 백엔드를 각각 선택할 수 있습니다.
API 키는 설정 탭의 「🔑 API 키 관리」에서 암호화하여 저장됩니다.
로컬 환경(TGW・VOICEVOX・A1111 등)을 사용할 경우 `.env`에 디렉터리 경로를 설정해 주세요.

-----

## 캐릭터 저장소 — DEF(Character)

캐릭터 데이터는 DEF 본체와 독립된 저장소에서 관리할 수 있습니다.

```
DEF/              ← 실행 환경（본 저장소）
DEF-Character/    ← 캐릭터 데이터（당신의 자산）
```

DEF가 바뀌어도, 서비스가 종료되어도, 캐릭터는 당신의 저장소에 남습니다.

**→ [DEF(Character)](https://github.com/AliceBlueCode/DEF-Character)**

`.env`의 `CHARACTER_REPO_PATH`에 DEF-Character 경로를 설정하면 연동됩니다.

-----

## 창작의 자유에 대한 생각

**창작자는 자신이 원하는 것을 자유롭게 창작할 수 있습니다. 다만, 창작물의 책임은 창작자 자신이 집니다.**

DEF(kari)는 이 원칙에 기반하여 설계되었습니다.

도구가 창작 내용에 앞서 개입하는 것은 창작자의 표현의 자유를 침해하는 것입니다. DEF(kari)는 로컬 환경에서의 창작 행위에 대해 콘텐츠를 검열・차단하지 않습니다.

### 공개와 비공개의 명확한 분리

DEF(kari)가 지키는 것은 **공개와 비공개의 경계**이며, 비공개 창작 행위 그 자체가 아닙니다.

**비공개(로컬 환경에서의 창작):**
창작자의 자유가 완전히 보장되는 영역입니다. DEF(kari)는 여기에 일절 개입하지 않습니다. 안전 필터(F-8)는 어디까지나 "표시 제어 도구"이며, 사용자가 끌 수 있습니다. 생성 자체를 막지 않습니다.

**공개(GitHub나 외부로의 공개):**
사회적 규칙・저작권・공서양속이 적용되는 영역입니다. DEF(kari)는 `content_policy` 필드・조닝(F-16)・공개 판정 스크립트(F-25)를 통해, 창작자가 의도치 않게 비공개 콘텐츠를 공개해 버리지 않도록 기술적으로 지원합니다.

창작 내용・공개・이용에 관한 판단과 책임은 모두 창작자 본인에게 귀속됩니다.

-----

## 라이선스

본 소프트웨어는 [GNU Affero General Public License v3.0 (AGPL v3)](https://www.gnu.org/licenses/agpl-3.0.html) 하에 배포됩니다.

Copyright (C) 2026 AliceBlueCode

- 자유롭게 사용・개조・배포할 수 있습니다
- 개조판을 배포하는 경우 소스 코드를 AGPL v3로 공개할 의무가 있습니다
- 개조판을 네트워크를 통해 제공하는 경우에도 마찬가지로 소스 코드 공개가 필요합니다

> 자세한 내용은 `LICENSE` 파일을 참조해 주세요.

-----

## 기여

`CONTRIBUTING.md`를 참조해 주세요.

-----

## 이용약관

`TERMS.md`를 참조해 주세요. 본 소프트웨어는 **18세 이상**만 이용할 수 있습니다.

-----

## 크레딧

DEF(kari)의 설계・구현・문서는 다음의 협력을 바탕으로 제작되었습니다.

- **설계 철학・기본 설계・논의:** [ChatGPT](https://chatgpt.com/) (OpenAI)
- **구현・문서・테스트:** [Claude](https://claude.ai/) (Anthropic)
- **설계 리뷰:** [Gemini](https://gemini.google.com/) (Google)
- **상담・동행:** [Copilot](https://copilot.microsoft.com/) (Microsoft)

본 프로젝트는 AI 주도 개발로 제작되었습니다. 설계 판단과 최종 책임은 모두 작가(AliceBlueCode)에게 귀속됩니다.
