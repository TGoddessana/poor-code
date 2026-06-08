from poor_code.domain.session import SessionService
from poor_code.domain.session.store import SessionStore
from poor_code.domain.session.models import SessionState, Cursor, Phase
from poor_code.cli import make_persist_on_step


def test_make_persist_on_step_writes_state_json(tmp_path):
    store = SessionStore(tmp_path)
    service = SessionService(store)
    session = service.start_session(tmp_path)
    persist = make_persist_on_step(store, service)
    st = SessionState(cursor=Cursor(phase=Phase.PLANNING, current_node="planner"))
    persist(st)
    reloaded = store.read_session_state(session.session_id)
    assert reloaded.cursor.current_node == "planner"
