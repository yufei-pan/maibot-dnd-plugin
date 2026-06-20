"""权限矩阵单元测试。"""

from __future__ import annotations

from dnd.session.permissions import can


def test_only_creator_restarts_stopped() -> None:
    session = {"status": "stopped", "creator_id": "c1"}
    assert can("c1", "restart", session, admin_ids=[], open_mode=False, enrolled=set()) is True
    assert can("p1", "restart", session, admin_ids=[], open_mode=False, enrolled={"p1"}) is False


def test_enrolled_can_stop_running() -> None:
    session = {"status": "running", "creator_id": "c1"}
    assert can("p1", "stop", session, admin_ids=[], open_mode=False, enrolled={"p1"}) is True
    assert can("x1", "stop", session, admin_ids=[], open_mode=False, enrolled={"p1"}) is False


def test_admin_can_lifecycle_without_being_creator() -> None:
    session = {"status": "setup", "creator_id": "c1"}
    assert can("admin1", "start", session, admin_ids=["admin1"], open_mode=False, enrolled=set()) is True
    assert can("admin1", "handoff", session, admin_ids=["admin1"], open_mode=False, enrolled=set()) is True


def test_enrolled_cannot_start_or_handoff() -> None:
    session = {"status": "setup", "creator_id": "c1"}
    enrolled = {"p1"}
    assert can("p1", "start", session, admin_ids=[], open_mode=False, enrolled=enrolled) is False
    assert can("p1", "handoff", session, admin_ids=[], open_mode=False, enrolled=enrolled) is False
    assert can("p1", "join", session, admin_ids=[], open_mode=False, enrolled=enrolled) is True


def test_proceed_requires_enrollment() -> None:
    session = {"status": "running", "creator_id": "c1"}
    assert can("c1", "proceed", session, admin_ids=[], open_mode=False, enrolled=set()) is False
    assert can("c1", "proceed", session, admin_ids=[], open_mode=False, enrolled={"c1"}) is True
    assert can("admin1", "proceed", session, admin_ids=["admin1"], open_mode=False, enrolled=set()) is False
    assert can("admin1", "proceed", session, admin_ids=["admin1"], open_mode=False, enrolled={"admin1"}) is True


def test_open_mode_grants_lifecycle_admin() -> None:
    session = {"status": "running", "creator_id": "c1"}
    assert can("stranger", "stop", session, admin_ids=[], open_mode=True, enrolled=set()) is True
    assert can("stranger", "handoff", session, admin_ids=[], open_mode=True, enrolled=set()) is True
    assert can("stranger", "proceed", session, admin_ids=[], open_mode=True, enrolled=set()) is False


def test_stop_only_when_running() -> None:
    session = {"status": "setup", "creator_id": "c1"}
    assert can("c1", "stop", session, admin_ids=[], open_mode=False, enrolled={"c1"}) is False


def test_new_allowed_without_session() -> None:
    assert can("anyone", "new", None, admin_ids=[], open_mode=False, enrolled=set()) is True


def test_restart_only_when_stopped() -> None:
    session = {"status": "running", "creator_id": "c1"}
    assert can("c1", "restart", session, admin_ids=[], open_mode=False, enrolled=set()) is False
