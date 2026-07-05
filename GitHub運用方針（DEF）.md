## GitHub運用方針（DEF）  
Version: Draft 0.1  
   
⸻  
   
## 1. 目的  
DEFは単なるソースコード管理ではない。  
GitHubを  
**知識・設計・人格（Character）の管理基盤**  
として利用する。  
GitHubそのものを、DEFの思想に沿った開発基盤として設計する。  
   
⸻  
   
## 2. 基本思想  
GitHubは以下を提供する。  
* Version管理  
* Branch管理  
* 査読（Pull Request）  
* Merge  
* Release  
これはDEFが採用する  
Branch → Chronicle → Main  
という思想と極めて親和性が高い。  
   
⸻  
   
## 3. リポジトリ構成  
将来的には以下のような構成を想定する。  
```
DEF/
    システム本体

DEF(Character)/
    Character定義
    Public Persona
    Prompt
    Memory

DEF(Origin)/
    公開Character
    Release対象

```
   
⸻  
   
## 4. Character管理  
Characterは独立した成果物とする。  
例  
```
characters/

    Hanfei/

        character.md
        public_persona.md
        history.md

    Mizuho/

        character.md
        public_persona.md
        history.md

    Ao/

        character.md
        public_persona.md
        history.md

```
Characterは  
* ソフトウェア  
* ドキュメント  
と同等にVersion管理される。  
   
⸻  
   
## 5. Branch思想  
Branchは失敗ではない。  
Branchは  
**Characterが歩み得たもう一つの可能性**  
**Characterが歩み得たもう一つの可能性**  
である。  
そのため  
Branchは削除するものではなく、  
保存される資産と考える。  
   
⸻  
   
## 6. GitHub Flow  
基本フロー  
```
Main

↓

Feature Branch

↓

Commit

↓

Pull Request

↓

Review

↓

Merge

```
DEFでは  
Feature Branchは  
Character Branch  
として扱うこともできる。  
   
⸻  
   
## 7. Pull Request  
Pull Requestは  
「変更提案」  
である。  
直接Mainへ反映しない。  
十分な査読を経て  
Main Chronicleへ統合する。  
   
⸻  
   
## 8. AI査読  
将来的にはAIが査読へ参加する。  
例  
```
Pull Request

↓

蒼
実装確認

↓

Claude
設計思想査読

↓

ChatGPT
可読性・保守性査読

↓

Gemini
創造性査読

↓

Owner
Merge判断

```
AIは  
Mergeを行わない。  
最後の判断者はOwnerである。  
   
⸻  
   
## 9. Public Persona判定  
Character変更後  
自動判定を行う。  
例  
```
Character更新

↓

Public Persona判定

↓

Privacy Scan

↓

Copyright Scan

↓

公開可能

↓

OriginへPull Request生成

```
公開不可の場合  
Branchとして保存する。  
破棄しない。  
   
⸻  
   
## 10. PushではなくPR  
DEFでは  
自動Pushは採用しない。  
理由  
* Mainを書き換えない  
* 人間が最終判断する  
* AIは提案者である  
そのため  
自動生成されるのは  
Pull Request  
とする。  
   
⸻  
   
## 11. Branch Protection  
Mainは保護する。  
想定設定  
* Direct Push禁止  
* Pull Request必須  
* Review必須  
* CI成功必須  
必要に応じて  
複数AIレビューを必須化する。  
   
⸻  
   
## 12. DEFとGitHub  
GitHubでは  
Forkによって  
別の世界線が生まれる。  
これはDEFにおける  
Branch  
と同義である。  
```
Main

↓

Fork

↓

別の進化

↓

Pull Request

↓

Mainへ還元

```
Branchには優劣は存在しない。  
Mainへ統合するかどうかを決定するのは  
Owner  
である。  
   
⸻  
   
## 13. 将来構想  
最終的にはGitHubを  
AI卓  
として利用する。  
Pull Requestには  
各AIが査読コメントを付与する。  
Ownerは  
それらを参考に  
Mergeを判断する。  
   
⸻  
   
## 14. Philosophy  
GitHubはソースコードを管理する。  
DEFは  
**人格をVersion管理する。**  
**人格をVersion管理する。**  
GitHubはBranchを管理する。  
DEFは  
**可能性を管理する。**  
**可能性を管理する。**  
GitHubはMergeする。  
DEFは  
**Characterの歴史を統合する。**  
**Characterの歴史を統合する。**  
最終的なMain Chronicleを選ぶのは、  
常にPlayer（Owner）である。  
この内容をベースに、将来的には「GitHub運用規約」「AI査読プロトコル」「Character CI/CD仕様」といった設計書へ発展させることもできると思います。  
