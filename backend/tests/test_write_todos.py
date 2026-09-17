"""待办写接口测试（SPEC-M2 §2.1 + 决策 A/B/C）。

数据底座 = data-samples（14 VTODO：11 顶层 + 3 子任务；q3-review-parent
挂 3 子（2 COMPLETED + 1 NEEDS-ACTION）；1 VEVENT）。
每个写测试顺手断言落盘文件可被 icalendar 重解析（数据主权底线）。
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar

from app.datastore import ics_store

UID_RE = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{4}@workbench\.local$")


def _post(client: TestClient, payload: dict):
    return client.post("/api/todos", params={"user": "tester"}, json=payload)


def _patch(client: TestClient, uid: str, payload: dict):
    return client.patch(f"/api/todos/{uid}", params={"user": "tester"}, json=payload)


def _action(client: TestClient, uid: str, action: str):
    return client.post(f"/api/todos/{uid}/{action}", params={"user": "tester"})


def _list(client: TestClient, **params):
    return client.get("/api/todos", params={"user": "tester", **params}).json()


def _read(tester_dir: Path) -> dict:
    return ics_store.read_calendar(tester_dir)


def _raw(tester_dir: Path) -> str:
    return (tester_dir / "calendar.ics").read_text(encoding="utf-8")


def _reparseable(tester_dir: Path) -> None:
    Calendar.from_ical((tester_dir / "calendar.ics").read_bytes())


def _top_uid(client: TestClient, part: str = "task-read-book") -> str:
    return next(i["uid"] for i in _list(client, scope="all")["items"] if part in i["uid"])


# ---------------------------------------------------------------- POST


def test_post_todo_minimal(client: TestClient, tester_dir: Path) -> None:
    r = _post(client, {"summary": "新建待办"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    t = body["data"]
    assert UID_RE.match(t["uid"]), t["uid"]
    assert t["summary"] == "新建待办"
    assert t["status"] == "NEEDS-ACTION" and t["completed"] is None
    assert t["important"] is False and t["urgent"] is False
    assert t["quadrant"] == "q4" and t["has_time"] == "unscheduled"
    assert t["created"] and t["dtstamp"]
    assert t["children"] == [] and t["progress"] is None
    _reparseable(tester_dir)
    stored = next(x for x in _read(tester_dir)["todos"] if x["uid"] == t["uid"])
    assert stored["summary"] == "新建待办"


def test_post_todo_full_fields_naive_as_shanghai(client: TestClient, tester_dir: Path) -> None:
    r = _post(client, {
        "summary": "全字段任务", "description": "描述文本",
        "important": True, "urgent": True,
        "due": "2026-09-20T18:00", "dtstart": "2026-09-20T14:00",
        "duration_minutes": 90, "categories": ["工作", "评审"],
    })
    t = r.json()["data"]
    assert t["quadrant"] == "q1" and t["has_time"] == "both"
    # naive 输入按 Asia/Shanghai 解释（SPEC-M2 §2.1）
    assert t["due"] == "2026-09-20T18:00:00+08:00"
    assert t["dtstart"] == "2026-09-20T14:00:00+08:00"
    assert t["duration_minutes"] == 90
    assert t["description"] == "描述文本"
    raw = _raw(tester_dir)
    assert "X-IMPORTANT:TRUE" in raw and "X-URGENT:TRUE" in raw
    assert "TZID=Asia/Shanghai:20260920T180000" in raw
    assert "工作" in raw and "评审" in raw
    _reparseable(tester_dir)


def test_post_todo_tz_aware_converted_to_shanghai(client: TestClient) -> None:
    r = _post(client, {"summary": "时区折算", "due": "2026-09-20T18:00:00+00:00"})
    assert r.json()["data"]["due"] == "2026-09-21T02:00:00+08:00"


def test_post_todo_all_day_value_date(client: TestClient, tester_dir: Path) -> None:
    r = _post(client, {
        "summary": "全天事项", "dtstart": "2026-09-20",
        "all_day": True, "duration_minutes": 2 * 1440,
    })
    t = r.json()["data"]
    assert t["all_day"] is True and t["dtstart"] == "2026-09-20"
    assert "DTSTART;VALUE=DATE:20260920" in _raw(tester_dir)


def test_post_todo_with_parent_returns_parent_node(client: TestClient) -> None:
    parent = next(i for i in _list(client, scope="all")["items"] if "q3-review-parent" in i["uid"])
    r = _post(client, {"summary": "第四个子任务", "parent_uid": parent["uid"]})
    node = r.json()["data"]
    assert node["uid"] == parent["uid"], "创建子任务应返回父顶层节点（进度服务端权威）"
    assert node["children_total"] == 4 and node["children_done"] == 2
    assert any(c["summary"] == "第四个子任务" for c in node["children"])


@pytest.mark.parametrize("payload,keyword", [
    ({"summary": "   "}, "summary"),                                   # 去空白后为空
    ({"summary": "x" * 201}, "summary"),                               # 长度 > 200
    ({"summary": "ok", "due": "2026-09-20T10:00",
      "dtstart": "2026-09-20T14:00"}, "due"),                          # due < dtstart
    ({"summary": "ok", "duration_minutes": 60}, "dtstart"),            # 只有 duration
    ({"summary": "ok", "dtstart": "2026-09-20T10:00",
      "duration_minutes": 0}, "duration_minutes"),                     # 非正整数
    ({"summary": "ok", "parent_uid": "no-such-parent@x"}, "父任务"),    # 父不存在
    ({"summary": "ok", "due": "九月二十号"}, "due"),                    # 非法 ISO
])
def test_post_todo_validation_422(client: TestClient, payload: dict, keyword: str) -> None:
    r = _post(client, payload)
    assert r.status_code == 422
    assert keyword in r.json()["detail"], r.json()["detail"]


def test_post_todo_parent_must_be_top_level(client: TestClient) -> None:
    """默认两级：给已是子任务的 uid 再挂子任务 → 422，detail 说明"两级"。"""
    parent = next(i for i in _list(client, scope="all")["items"] if "q3-review-parent" in i["uid"])
    child = parent["children"][0]
    r = _post(client, {"summary": "孙任务", "parent_uid": child["uid"]})
    assert r.status_code == 422
    assert "两级" in r.json()["detail"]


def test_post_todo_uid_conflict_500_keeps_file(
    client: TestClient, tester_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uid 冲突（理论不该发生）→ 500 且旧文件保留。"""
    from app.service import todo_write

    existing = _list(client, scope="all")["items"][0]["uid"]
    monkeypatch.setattr(todo_write, "new_uid", lambda: existing)
    before = (tester_dir / "calendar.ics").read_bytes()
    r = _post(client, {"summary": "冲突任务"})
    assert r.status_code == 500
    assert (tester_dir / "calendar.ics").read_bytes() == before


# ---------------------------------------------------------------- PATCH


def test_patch_partial_keeps_other_components(client: TestClient, tester_dir: Path) -> None:
    """往返 diff（SPEC-M2 §3）：改一条，其余组件逐条字段无损。"""
    before = _read(tester_dir)
    uid = _top_uid(client)
    r = _patch(client, uid, {"summary": "读书(改)", "important": True})
    assert r.status_code == 200
    node = r.json()["data"]
    assert node["uid"] == uid and node["summary"] == "读书(改)"
    assert node["important"] is True and node["quadrant"] == "q2"
    after = _read(tester_dir)
    for b in before["todos"]:
        a = next(t for t in after["todos"] if t["uid"] == b["uid"])
        if b["uid"] == uid:
            for k, v in b.items():
                if k in ("summary", "important", "quadrant", "dtstamp"):
                    continue  # dtstamp 修改时刷新（RFC 5545），属预期变化
                assert a[k] == v, k
            assert a["summary"] == "读书(改)" and a["important"] is True
        else:
            assert a == b, f"未修改组件字段丢失: {b['uid']}"
    assert after["events"] == before["events"]
    _reparseable(tester_dir)


def test_patch_rejects_status(client: TestClient) -> None:
    """决策 B：PATCH 不接受 status → 422，detail 指引专用动作。"""
    uid = _top_uid(client)
    r = _patch(client, uid, {"status": "COMPLETED"})
    assert r.status_code == 422
    assert "status" in r.json()["detail"]
    assert "complete" in r.json()["detail"]


def test_patch_unknown_field_rejected(client: TestClient) -> None:
    r = _patch(client, _top_uid(client), {"priority": 1})
    assert r.status_code == 422 and "不接受的字段" in r.json()["detail"]


def test_patch_explicit_null_clears_due(client: TestClient, tester_dir: Path) -> None:
    """显式 null = 清除字段：DUE 从文件里消失（未排期化）。"""
    uid = _top_uid(client, "pay-insurance")  # 样例中该条有 DUE
    r = _patch(client, uid, {"due": None})
    assert r.json()["data"]["due"] is None
    assert r.json()["data"]["has_time"] == "unscheduled"
    stored = next(t for t in _read(tester_dir)["todos"] if t["uid"] == uid)
    assert stored["due"] is None


def test_patch_attach_and_detach_parent(client: TestClient) -> None:
    parent = next(i for i in _list(client, scope="all")["items"] if "q3-review-parent" in i["uid"])
    uid = _top_uid(client)
    # 挂为子任务 → 返回父节点
    node = _patch(client, uid, {"parent_uid": parent["uid"]}).json()["data"]
    assert node["uid"] == parent["uid"]
    assert any(c["uid"] == uid for c in node["children"])
    # 解除 → 变回顶层
    node2 = _patch(client, uid, {"parent_uid": None}).json()["data"]
    assert node2["uid"] == uid and node2["parent_uid"] is None


def test_patch_parent_with_children_rejected(client: TestClient) -> None:
    """已有子任务的待办不能再挂为别人的子任务（默认两级）。"""
    parent = next(i for i in _list(client, scope="all")["items"] if "q3-review-parent" in i["uid"])
    other = _top_uid(client)
    r = _patch(client, parent["uid"], {"parent_uid": other})
    assert r.status_code == 422 and "两级" in r.json()["detail"]


def test_patch_self_as_parent_rejected(client: TestClient) -> None:
    uid = _top_uid(client)
    r = _patch(client, uid, {"parent_uid": uid})
    assert r.status_code == 422 and "自己" in r.json()["detail"]


def test_patch_404(client: TestClient) -> None:
    r = _patch(client, "no-such@x", {"summary": "x"})
    assert r.status_code == 404 and "不存在" in r.json()["detail"]


# ---------------------------------------------------------------- 状态动作


def test_complete_idempotent_no_rewrite(client: TestClient, tester_dir: Path) -> None:
    uid = _top_uid(client)
    t1 = _action(client, uid, "complete").json()["data"]
    assert t1["status"] == "COMPLETED" and t1["completed"]
    bytes1 = (tester_dir / "calendar.ics").read_bytes()
    t2 = _action(client, uid, "complete").json()["data"]
    assert t2["completed"] == t1["completed"], "幂等：COMPLETED 时间戳不变"
    assert (tester_dir / "calendar.ics").read_bytes() == bytes1, "幂等：不落盘不产生备份"
    # 决策 A：完成后默认列表消失、归档区可见
    assert not any(i["uid"] == uid for i in _list(client)["items"])
    assert any(i["uid"] == uid and i["status"] == "COMPLETED"
               for i in _list(client, scope="archived")["items"])


def test_reopen_clears_completed(client: TestClient, tester_dir: Path) -> None:
    uid = _top_uid(client)
    _action(client, uid, "complete")
    t = _action(client, uid, "reopen").json()["data"]
    assert t["status"] == "NEEDS-ACTION" and t["completed"] is None
    stored = next(x for x in _read(tester_dir)["todos"] if x["uid"] == uid)
    assert stored["completed"] is None
    assert stored["status"] == "NEEDS-ACTION"
    _reparseable(tester_dir)


def test_abandon_and_reopen_cancelled(client: TestClient) -> None:
    """决策 #1：放弃 = STATUS:CANCELLED；归档区可见；reopen 兼作恢复。"""
    uid = _top_uid(client)
    t = _action(client, uid, "abandon").json()["data"]
    assert t["status"] == "CANCELLED"
    assert any(i["uid"] == uid for i in _list(client, scope="archived")["items"])
    assert not any(i["uid"] == uid for i in _list(client)["items"])
    t2 = _action(client, uid, "reopen").json()["data"]
    assert t2["status"] == "NEEDS-ACTION"
    assert any(i["uid"] == uid for i in _list(client)["items"])


def test_abandon_clears_completed_timestamp(client: TestClient, tester_dir: Path) -> None:
    uid = _top_uid(client)
    _action(client, uid, "complete")
    _action(client, uid, "abandon")
    stored = next(x for x in _read(tester_dir)["todos"] if x["uid"] == uid)
    assert stored["status"] == "CANCELLED" and stored["completed"] is None


def test_action_404(client: TestClient) -> None:
    for action in ("complete", "reopen", "abandon"):
        r = _action(client, "no-such@x", action)
        assert r.status_code == 404 and "不存在" in r.json()["detail"]


def test_complete_child_updates_parent_progress(client: TestClient) -> None:
    """勾选子任务 → 响应 = 父顶层节点，进度已联动（服务端权威计算）。"""
    parent = next(i for i in _list(client, scope="all")["items"] if "q3-review-parent" in i["uid"])
    child3 = next(c for c in parent["children"] if c["status"] == "NEEDS-ACTION")
    node = _action(client, child3["uid"], "complete").json()["data"]
    assert node["uid"] == parent["uid"]
    assert node["children_done"] == 3 and node["children_total"] == 3
    assert node["progress"] == 1.0


def test_abandon_child_excluded_from_progress(client: TestClient) -> None:
    """SPEC-M2 §1：CANCELLED 不计入分母——放弃的子任务不拖累进度。"""
    parent = next(i for i in _list(client, scope="all")["items"] if "q3-review-parent" in i["uid"])
    child3 = next(c for c in parent["children"] if c["status"] == "NEEDS-ACTION")
    node = _action(client, child3["uid"], "abandon").json()["data"]
    assert node["children_total"] == 2, "分母排除 CANCELLED"
    assert node["children_done"] == 2
    assert node["children_cancelled"] == 1
    assert node["progress"] == 1.0, "放弃项不拖累进度（2/2 而非 2/3）"
    assert len(node["children"]) == 3, "children 数组仍含放弃项（前端样式需要）"


# ---------------------------------------------------------------- scope（决策 A）


def test_scope_param_semantics(client: TestClient) -> None:
    uid = _top_uid(client)
    _action(client, uid, "complete")
    active = _list(client)
    archived = _list(client, scope="archived")
    everything = _list(client, scope="all")
    assert not any(i["uid"] == uid for i in active["items"])
    assert any(i["uid"] == uid and i["status"] == "COMPLETED" for i in archived["items"])
    assert everything["count"] == active["count"] + archived["count"]
    # 只滤顶层：父任务（NEEDS-ACTION）仍在 active，其 COMPLETED 子任务照常挂在 children
    active_parent = next(i for i in active["items"] if "q3-review-parent" in i["uid"])
    assert len(active_parent["children"]) == 3
    assert sum(1 for c in active_parent["children"] if c["status"] == "COMPLETED") == 2
    # 非法 scope → 422
    assert client.get("/api/todos", params={"user": "tester", "scope": "bogus"}).status_code == 422


def test_default_scope_is_active(client: TestClient) -> None:
    """缺省 = active；样例顶层无归档项 → 与 M1 行为一致（count=11）。"""
    assert _list(client)["count"] == 11 == _list(client, scope="all")["count"]
    assert _list(client, scope="archived")["count"] == 0


# ---------------------------------------------------------------- DELETE


def test_delete_leaf_and_others_intact(client: TestClient, tester_dir: Path) -> None:
    before = _read(tester_dir)
    uid = _top_uid(client)
    r = client.delete(f"/api/todos/{uid}", params={"user": "tester"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "data": {"deleted": [uid]}}
    after = _read(tester_dir)
    assert {t["uid"] for t in after["todos"]} == {t["uid"] for t in before["todos"]} - {uid}
    # 往返 diff：其余 13 条逐条全等、事件不变
    for b in before["todos"]:
        if b["uid"] == uid:
            continue
        a = next(t for t in after["todos"] if t["uid"] == b["uid"])
        assert a == b, f"未修改组件字段丢失: {b['uid']}"
    assert after["events"] == before["events"]
    _reparseable(tester_dir)
    assert client.get(f"/api/todos/{uid}", params={"user": "tester"}).status_code == 404


def test_delete_parent_cascades_children(client: TestClient, tester_dir: Path) -> None:
    """决策 C：删除父任务级联物理删除全部子任务，返回被删 uid 数组。"""
    parent = next(i for i in _list(client, scope="all")["items"] if "q3-review-parent" in i["uid"])
    child_uids = [c["uid"] for c in parent["children"]]
    r = client.delete(f"/api/todos/{parent['uid']}", params={"user": "tester"})
    deleted = set(r.json()["data"]["deleted"])
    assert deleted == {parent["uid"], *child_uids}
    after_uids = {t["uid"] for t in _read(tester_dir)["todos"]}
    assert not (deleted & after_uids), "父 + 全部子任务应物理移除"
    assert len(after_uids) == 14 - 1 - len(child_uids)
    _reparseable(tester_dir)


def test_delete_404(client: TestClient) -> None:
    r = client.delete("/api/todos/no-such@x", params={"user": "tester"})
    assert r.status_code == 404 and "不存在" in r.json()["detail"]


# ---------------------------------------------------------------- CORS


def test_cors_preflight_allows_post(client: TestClient) -> None:
    """M1 的 allow_methods=['GET'] 是写接口硬阻塞，M2 已扩全。"""
    r = client.options(
        "/api/todos",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 200
    assert "POST" in r.headers.get("access-control-allow-methods", "")
