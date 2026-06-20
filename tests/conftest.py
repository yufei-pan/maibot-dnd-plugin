"""pytest 配置：异步测试仅使用 asyncio 后端。"""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
