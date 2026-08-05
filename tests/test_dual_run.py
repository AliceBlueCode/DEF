"""dual_run.py の起動設定のテスト（8.15対策: WS側のメッセージサイズ上限）。

TestClientはASGI呼び出しを直接シミュレートするためuvicornのプロトコルレベル制限
（ws_max_size）はTestClient経由では検証できない。ここではuvicorn.Config/Serverを
モックし、正しい引数が渡っていることだけを確認する。
"""

import asyncio
from unittest.mock import patch


def test_dual_run_configures_ws_max_size():
    """local/public両方のuvicorn.Configにws_max_sizeが渡されていること
    （HTTP側のSessionBodySizeLimitMiddleware・512KBと揃える。以前はws_max_sizeを
    指定しておらずuvicornのデフォルト16MBのままだった）。"""
    from def_kari.api import dual_run
    from def_kari.api.main import _SESSION_BODY_SIZE_LIMIT

    captured_configs = []

    class _FakeConfig:
        def __init__(self, app, **kwargs):
            captured_configs.append(kwargs)

    class _FakeServer:
        def __init__(self, config):
            pass

        async def serve(self):
            return

    with patch.object(dual_run.uvicorn, "Config", _FakeConfig), \
         patch.object(dual_run.uvicorn, "Server", _FakeServer):
        asyncio.run(dual_run._run("127.0.0.1", 8511, "0.0.0.0", 8512))

    assert len(captured_configs) == 2
    for kwargs in captured_configs:
        assert kwargs.get("ws_max_size") == _SESSION_BODY_SIZE_LIMIT
