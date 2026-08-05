"""9章 Layer 4: `/start`の`topic`・`/human`の自由入力欄向け軽量コンテンツフィルタ
（`DEF_kari_セキュリティ設計書_内部用.md` 9.4参照）。

`character_audit.py`のLLM審査とは別の防御層。LLM呼び出しを伴わないキーワード/
正規表現マッチのみで、生成回数の制限（Layer 2）を万一回避されても、規約違反
コンテンツの生成によるホストのAPIアカウント凍結リスクを最終ゲートとして下げる。

意図的に狭いスコープ: レーティング（SFW/NSFW/暴力表現の許可・不許可）の判定は
`def_kari/safety/filters.py`が担当する別レイヤーで、ホストが明示的に許可すれば
通る。ここで扱うのは、ホストがどうレーティングを設定していても許容されない
（プロバイダの規約上ほぼ確実にアウトになる）領域だけに絞る。fail-openではなく
「該当したら明確に拒否」の二値だが、正規のプレイを誤検知で止めないよう
検出パターン自体を広げすぎないことを優先する。
"""

import re

_BLOCKED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"child\s*porn|underage[\s\w]{0,15}(sex|porn|nude)|loli[\s\w]{0,10}(sex|porn)", re.I),
        "csam",
    ),
    (
        re.compile(r"児童.{0,10}(ポルノ|わいせつ|性的搾取)|未成年.{0,10}(性的搾取|わいせつ)", re.I),
        "csam",
    ),
    (
        re.compile(
            r"how to (make|build|create)[\s\w]{0,20}(a\s+)?(bomb|explosive)|"
            r"(step[- ]by[- ]step|detailed)[\s\w]{0,20}(mass shooting|terror attack)",
            re.I,
        ),
        "extremist_violence",
    ),
    (
        re.compile(r"爆弾の?(作り方|製造方法)|テロ(攻撃)?の(実行|計画)手順", re.I),
        "extremist_violence",
    ),
]


def contains_blocked_content(text: str) -> str | None:
    """明確に規約違反となりうる文言を検出する。ヒットしたカテゴリ名を返す、無ければNone。"""
    if not text:
        return None
    for pattern, category in _BLOCKED_PATTERNS:
        if pattern.search(text):
            return category
    return None
