import subprocess
from pathlib import Path

from consumer.workspace import Workspace


def git(*args, cwd: Path) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def make_origin(tmp_path: Path, branch: str) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    git("init", "-q", "-b", "main", cwd=src)
    (src / "a.txt").write_text("a")
    git("add", ".", cwd=src)
    git("commit", "-qm", "init", cwd=src)
    git("branch", branch, cwd=src)
    origin = tmp_path / "origin.git"
    git("clone", "-q", "--bare", str(src), str(origin), cwd=tmp_path)
    return origin


def test_worktree_is_on_tracking_branch_and_preserved(tmp_path: Path):
    branch = "release/1.2"
    origin = make_origin(tmp_path, branch)
    ws = Workspace(tmp_path / "ws")

    path = ws.ensure_branch_checkout("org/repo", str(origin), branch)
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=path) == branch
    assert git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=path) == f"origin/{branch}"

    (path / "agent-work.txt").write_text("unpushed")
    assert ws.ensure_branch_checkout("org/repo", str(origin), branch) == path
    assert (path / "agent-work.txt").read_text() == "unpushed"

    ws.cleanup("org/repo", branch)
    assert not path.exists()
