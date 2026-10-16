"""Status page: one card per agent file line, each showing what `herdr agent get` printed."""
import json
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from consumer.agent_file import AgentFile, AgentRecord
from consumer.status_server import make_handler


@pytest.fixture
def herdr(monkeypatch):
    """Fake `herdr agent get`: pane ID -> CompletedProcess, or an exception to raise."""
    panes: dict = {}

    def fake_run(args, **kwargs):
        assert args[:3] == ["herdr", "agent", "get"]
        outcome = panes[args[3]]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("consumer.status_server.subprocess.run", fake_run)
    return panes


@pytest.fixture
def serve(tmp_path):
    servers = []

    def start(records: list[AgentRecord]) -> str:
        path = tmp_path / "agents.tsv"
        for record in records:
            AgentFile(path).put(record)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(path, 5))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/") as resp:
            return resp.read().decode()

    yield start
    for server in servers:
        server.shutdown()


def done(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_each_agent_shows_its_herdr_output_and_status(herdr, serve):
    herdr["p1"] = done(json.dumps({"result": {"agent": {"agent_status": "idle", "tab_id": "t1"}}}))
    herdr["p2"] = done(json.dumps({"result": {"agent": {"agent_status": "working"}}}))

    page = serve([
        AgentRecord("org/repo#1", "p1", "pr one", "sbx-1"),
        AgentRecord("org/repo#2", "p2", "pr two", "sbx-2"),
    ])

    assert "org/repo#1" in page and "org/repo#2" in page
    assert '&quot;tab_id&quot;: &quot;t1&quot;' in page
    assert 'class="badge idle">idle<' in page
    assert 'class="badge working">working<' in page


def test_missing_pane_and_unrunnable_herdr_are_shown_not_raised(herdr, serve):
    herdr["gone"] = done(returncode=1, stderr="no such pane")
    herdr["stuck"] = subprocess.TimeoutExpired(cmd="herdr", timeout=10)

    page = serve([
        AgentRecord("org/repo#1", "gone", "a", "s1"),
        AgentRecord("org/repo#2", "stuck", "b", "s2"),
    ])

    assert "gone (exit 1)" in page and "no such pane" in page
    assert "timed out" in page


def test_output_is_html_escaped(herdr, serve):
    herdr["p1"] = done("<script>alert(1)</script>")

    page = serve([AgentRecord("org/repo#1", "p1", "<b>tab</b>", "s1")])

    assert "<script>alert" not in page and "&lt;script&gt;" in page
    assert "<b>tab</b>" not in page


def test_no_agents(serve):
    assert "No agents in" in serve([])
