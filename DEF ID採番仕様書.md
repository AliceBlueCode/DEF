## DEF ID採番仕様書  
Version: Draft 0.1  
   
⸻  
   
## 1. 目的  
DEFでは、Character・Branch・Instanceを明確に区別するため、それぞれ独立したIDを採番する。  
本仕様は、DEF全体で共通して利用するID体系を定義する。  
   
⸻  
   
## 2. 設計思想  
DEFでは人格を以下の三層構造として管理する。  
```
Character
    ↓
Branch
    ↓
Instance

```
それぞれは異なる役割を持つ。  
* Character … 「誰であるか」  
* Branch … 「どの人生を歩んだか」  
* Instance … 「現在動作している個体」  
この三者は混同しない。  
   
⸻  
   
## 3. Character ID  
## 目的  
Characterそのものを一意に識別する。  
Character IDは生成後、変更しない。  
   
⸻  
   
## フォーマット  
```
<CharacterName>_<YYYYMMDD>

```
   
⸻  
   
## 例  
```
Hanfei_20260611
Mizuho_20260702
Ao_20260618

```
   
⸻  
   
## 採番ルール  
Character生成日を使用する。  
同名Characterが将来作成された場合でも、  
生成日が異なるため重複しない。  
   
⸻  
   
## 4. Branch ID  
## 目的  
Characterが辿った歴史・世界線を識別する。  
BranchはCharacterとは独立して複数存在できる。  
   
⸻  
   
## フォーマット  
```
<BranchName>_<YYYYMMDD>

```
   
⸻  
   
## 例  
```
Main_20260701
InformationBroker_20260712
Retired_20260801

```
   
⸻  
   
## 採番ルール  
Branch生成日を使用する。  
同名Branchが生成された場合でも、  
生成日によって一意性を保証する。  
   
⸻  
   
## 5. Instance ID  
## 目的  
実際に稼働しているAI個体を識別する。  
Instanceは永続人格ではない。  
実行毎に生成される。  
   
⸻  
   
## フォーマット  
```
000001

```
6桁固定のゼロ埋め整数。  
   
⸻  
   
## 例  
```
000001
000002
000003

```
   
⸻  
   
## 採番ルール  
Character × Branchごとに管理する。  
Instance生成毎に連番をインクリメントする。  
欠番は許容する。  
採番済み番号は再利用しない。  
   
⸻  
   
## 6. 完全識別子  
Character・Branch・Instanceを組み合わせることで、  
DEF内の個体を完全に識別できる。  
   
⸻  
   
## フォーマット  
```
<CharacterID>/<BranchID>/<InstanceID>

```
   
⸻  
   
## 例  
```
Hanfei_20260611/Main_20260701/000001
Mizuho_20260702/InformationBroker_20260712/000154

```
   
⸻  
   
## 7. Forkとの関係  
GitHubにおけるForkは、  
DEFではBranchの概念に近い。  
ForkされたCharacterは、  
Character IDを保持したまま、  
新しいBranch IDを持つ。  
   
⸻  
   
例  
```
Character
Hanfei_20260611

↓

Main_20260701

↓

LegalReform_20260815

```
Character IDは変わらない。  
Branchのみ追加される。  
   
⸻  
   
## 8. UUIDを採用しない理由  
DEFでは、  
機械的な一意性だけでなく、  
人間が識別可能であることを重視する。  
例えば  
```
83b79e24-a2d1-4b9e...

```
よりも  
```
Hanfei_20260611

```
の方が、  
誰のデータかを即座に理解できる。  
これは、  
デバッグ・査読・運用・履歴追跡において大きな利点となる。  
   
⸻  
   
## 9. Philosophy  
Character IDは、  
人格の存在を表す。  
Branch IDは、  
人格が歩んだ歴史を表す。  
Instance IDは、  
現在動作している個体を表す。  
DEFは、  
人格・歴史・個体を分離して管理することで、  
Characterの連続性と可能性を両立する。  
