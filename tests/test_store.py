from pathlib import Path

from dnd.store import SessionStore


def test_create_session_layout(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    rec = store.create_session(stream_id="g1", title="Test Campaign", creator_id="u1")
    assert rec.status == "setup"
    assert (rec.root / "bible" / "world.md").exists()
    assert (rec.root / "session.toml").exists()
    loaded = store.load_session(rec.session_id, stream_id="g1")
    assert loaded.creator_id == "u1"
