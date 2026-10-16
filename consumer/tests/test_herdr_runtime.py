"""The real adapter: every subprocess failure surfaces as `AgentRuntimeError`, and `sbx list --json` parses."""
import subprocess

import pytest
from consumer.agent_runtime import AgentRuntimeError, PromptTimeout
from consumer.herdr_runtime import HerdrSbxRuntime


@pytest.fixture
def run_raises(monkeypatch):
    def arrange(exc: BaseException) -> None:
        def fake_run(args, **kwargs):
            raise exc

        monkeypatch.setattr("consumer.herdr_runtime.subprocess.run", fake_run)

    return arrange


TIMEOUT = subprocess.TimeoutExpired(cmd="herdr", timeout=1)


@pytest.mark.parametrize("exc", [TIMEOUT, FileNotFoundError("herdr"), PermissionError("herdr")])
def test_agent_info_lookup_that_cannot_run_raises_instead_of_reporting_the_pane_gone(run_raises, exc):
    run_raises(exc)

    with pytest.raises(AgentRuntimeError) as info:
        HerdrSbxRuntime().get_agent_info("pane-1")
    assert not isinstance(info.value, PromptTimeout)


@pytest.mark.parametrize("exc", [TIMEOUT, FileNotFoundError("sbx"), PermissionError("sbx")])
def test_sbx_commands_that_cannot_run_raise_agent_runtime_error(run_raises, exc):
    run_raises(exc)

    with pytest.raises(AgentRuntimeError):
        HerdrSbxRuntime().stop_sandbox("sbx-1")
    with pytest.raises(AgentRuntimeError):
        HerdrSbxRuntime().set_secret("sbx-1", "tok")


def test_prompt_timeout_raises_prompt_timeout(run_raises):
    run_raises(TIMEOUT)

    with pytest.raises(PromptTimeout):
        HerdrSbxRuntime().prompt("pane-1", "hello")


def test_token_is_redacted_from_timeout_errors(run_raises):
    run_raises(TIMEOUT)

    with pytest.raises(AgentRuntimeError) as info:
        HerdrSbxRuntime().set_secret("sbx-1", "tok-secret")
    assert "tok-secret" not in str(info.value)



def run_returns(monkeypatch, *stdouts: str) -> list[list[str]]:
    """Fake every command; `sbx list --json` prints each of `stdouts` in turn (the last repeats)."""
    calls, listings = [], list(stdouts)

    def fake_run(args, **kwargs):
        calls.append(args)
        out = listings.pop(0) if len(listings) > 1 else listings[0]
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr("consumer.herdr_runtime.subprocess.run", fake_run)
    return calls


def runtime(timeout: float = 0) -> HerdrSbxRuntime:
    return HerdrSbxRuntime(sandbox_listed_timeout_seconds=timeout, sandbox_listed_poll_interval_seconds=0)


LABEL = "sbx claude-code 5d563a"


@pytest.mark.parametrize("stdout", [
    '{"sandboxes": [{"name": "herdr-claude-code-111111"}, {"name": "herdr-claude-code-5d563a9f"}]}',
    '[{"name": "herdr-claude-code-111111"}, {"name": "herdr-claude-code-5d563a9f"}]',
    '{\n  "name": "herdr-claude-code-111111"\n}\n{\n  "name": "herdr-claude-code-5d563a9f"\n}\n',
])
def test_sandbox_is_the_listed_name_containing_the_tab_labels_last_word(monkeypatch, stdout):
    run_returns(monkeypatch, stdout)

    assert runtime()._sandbox_named(LABEL) == "herdr-claude-code-5d563a9f"


def test_sandbox_not_listed_yet_is_waited_for(monkeypatch):
    calls = run_returns(
        monkeypatch,
        '{"sandboxes": [{"name": "herdr-claude-code-111111"}]}',
        '{"sandboxes": [{"name": "herdr-claude-code-111111"}, {"name": "herdr-claude-code-5d563a9f"}]}',
    )

    assert runtime(timeout=5)._sandbox_named(LABEL) == "herdr-claude-code-5d563a9f"
    assert len(calls) == 2


def test_sandbox_never_listed_raises_with_the_names_seen(monkeypatch):
    run_returns(monkeypatch, '{"sandboxes": [{"name": "herdr-claude-code-111111"}]}')

    with pytest.raises(AgentRuntimeError, match="herdr-claude-code-111111"):
        runtime()._sandbox_named(LABEL)


def test_several_matching_sandboxes_raise_instead_of_guessing(monkeypatch):
    run_returns(monkeypatch, '{"sandboxes": [{"name": "a-5d563a"}, {"name": "b-5d563a"}]}')

    with pytest.raises(AgentRuntimeError, match="several"):
        runtime(timeout=5)._sandbox_named(LABEL)


def test_unparseable_sbx_list_output_raises_agent_runtime_error(monkeypatch):
    run_returns(monkeypatch, '{"sandboxes": []}\nUpdate available!\n')

    with pytest.raises(AgentRuntimeError, match="Update available"):
        runtime()._sandbox_named(LABEL)
