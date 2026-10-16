"""The startup prompt is the only way a Coordinator learns which branch to work on."""
from consumer.prompts import startup_prompt


def test_startup_prompt_checks_out_the_pull_request_with_gh_first():
    prompt = startup_prompt("org/repo", 7, "feature/x")

    assert prompt.index("gh pr checkout 7 --force") < prompt.index("For each piece of Feedback")
    assert "git fetch" not in prompt and "git checkout" not in prompt


def test_startup_prompt_refuses_feedback_when_the_checkout_fails():
    prompt = startup_prompt("org/repo", 7, "feature/x")

    assert "If that command fails, do not act on any Feedback" in prompt
    assert "checkout of `feature/x` failed" in prompt


def test_startup_prompt_still_pushes_with_an_explicit_refspec():
    assert "git push origin HEAD:feature/x" in startup_prompt("org/repo", 7, "feature/x")
