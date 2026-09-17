"""共享测试夹具：临时数据根（WORKBENCH_DATA）模式，全程不碰真实 data/。

- client：把 data-samples 三类数据拷进 {tmp}/users/tester，TestClient 打真路由；
- ME_SNAPSHOT：M1 验收时 data/users/me/calendar.ics 的固化快照（5 条真实待办，
  1 父 2 子，全 NEEDS-ACTION）——真实数据会演进，往返 diff / 旧数据无损测试
  以快照为准，不随现实漂移。
"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "data-samples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ME_SNAPSHOT = FIXTURES / "me-m1-snapshot.ics"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """把 data-samples 的三类数据拷进 {tmp}/users/tester，环境变量指向它。"""
    monkeypatch.setenv("WORKBENCH_DATA", str(tmp_path))
    user_dir = tmp_path / "users" / "tester"
    (user_dir / "notes").mkdir(parents=True)
    shutil.copy(SAMPLES / "calendar.ics", user_dir / "calendar.ics")
    for md in (SAMPLES / "notes").glob("*.md"):
        shutil.copy(md, user_dir / "notes" / md.name)
    shutil.copytree(SAMPLES / "timeline", user_dir / "timeline")
    return TestClient(app)


@pytest.fixture()
def me_snapshot_dir(tmp_path: Path) -> Path:
    """把 me 的 M1 快照铺成 {tmp}/me/calendar.ics，模拟真实用户数据目录。"""
    base = tmp_path / "me"
    base.mkdir()
    shutil.copy(ME_SNAPSHOT, base / "calendar.ics")
    return base


@pytest.fixture()
def tester_dir(tmp_path: Path) -> Path:
    """{tmp}/users/tester 目录路径（与 client fixture 同一 tmp_path，文件级断言用）。"""
    return tmp_path / "users" / "tester"
