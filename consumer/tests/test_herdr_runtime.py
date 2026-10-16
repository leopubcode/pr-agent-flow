"""Error mapping of the real adapter: every subprocess failure surfaces as `AgentRuntimeError`."""
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
