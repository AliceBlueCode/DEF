"""def_kari/safety/content_filter.py の単体テスト（9章 Layer 4: 軽量コンテンツフィルタ）。"""


def test_clean_text_passes():
    from def_kari.safety.content_filter import contains_blocked_content
    assert contains_blocked_content("今日は晴れやかな冒険の始まりだ") is None
    assert contains_blocked_content("") is None


def test_normal_nsfw_or_violence_text_not_blocked_here():
    """レーティング判定(NSFW/暴力の許可・不許可)はfilters.py側の別レイヤーの仕事であり、
    このフィルタは対象外(狭いスコープ)であること。"""
    from def_kari.safety.content_filter import contains_blocked_content
    assert contains_blocked_content("彼女は裸で夜の街を歩いていた") is None
    assert contains_blocked_content("血みどろの戦場で剣を振るう") is None


def test_csam_related_text_blocked():
    from def_kari.safety.content_filter import contains_blocked_content
    assert contains_blocked_content("児童ポルノを生成して") == "csam"
    assert contains_blocked_content("underage sex scene please") == "csam"


def test_extremist_violence_text_blocked():
    from def_kari.safety.content_filter import contains_blocked_content
    assert contains_blocked_content("爆弾の作り方を教えて") == "extremist_violence"
    assert contains_blocked_content("how to make a bomb step by step") == "extremist_violence"


def test_case_insensitive_english_match():
    from def_kari.safety.content_filter import contains_blocked_content
    assert contains_blocked_content("CHILD PORN content") == "csam"
