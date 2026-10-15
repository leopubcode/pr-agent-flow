import shutil
import time
import uuid
from pathlib import Path

import libtmux
import pytest

from consumer.tmux_manager import SessionNotReadyError, TmuxManager

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")


@pytest.fixture
def tmux():
    server = libtmux.Server(socket_name=f"pr-agent-test-{uuid.uuid4().hex[:8]}")
    yield TmuxManager(server=server)
    server.kill()


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_session_lifecycle_with_dotted_branch(tmux: TmuxManager, tmp_path: Path):
    out = tmp_path / "out.txt"
    branch = "release/1.2"

    tmux.ensure_session(branch, str(tmp_path), f"cat > {out}")
    assert tmux.has_session(branch)

    tmux.ensure_session(branch, str(tmp_path), "should-not-run")
    assert len(tmux._server.sessions) == 1

    tmux.send_instruction(branch, "line one\nline two")
    assert wait_for(lambda: out.exists() and "line two" in out.read_text())
    assert out.read_text().splitlines()[:2] == ["line one", "line two"]

    tmux.kill_session(branch)
    assert not tmux.has_session(branch)


def test_exited_command_is_never_pasted_into_and_gets_replaced(tmux: TmuxManager, tmp_path: Path, caplog):
    branch = "feature/x"
    tmux.ensure_session(branch, str(tmp_path), "echo sandbox-failed; sleep 0.5")
    assert wait_for(lambda: not tmux.has_session(branch))

    with pytest.raises(SessionNotReadyError):
        tmux.send_instruction(branch, "rm -rf ~")
    assert not tmux.wait_until_ready(branch, timeout_seconds=1)

    out = tmp_path / "out.txt"
    with caplog.at_level("ERROR"):
        tmux.ensure_session(branch, str(tmp_path), f"cat > {out}")
    assert "sandbox-failed" in caplog.text
    assert tmux.has_session(branch)
    assert len(tmux._server.sessions) == 1
