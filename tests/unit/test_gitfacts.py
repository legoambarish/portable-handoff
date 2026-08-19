"""Coverage for unusual repository states that ``gitfacts`` must describe
honestly rather than guess at.

Each test name states the property being protected, matching the convention
in ``test_hardening.py``: these are regression tests for situations a capsule
could otherwise misreport, not just exercises of the happy path.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from portable_handoff.bounds import DEFAULT_BOUNDS
from portable_handoff.gitfacts import collect_git_facts, find_repo_root, project_from_facts


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "Test")


def _commit(path: Path, filename: str, content: str, message: str) -> str:
    (path / filename).write_text(content, encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", message)
    return _git(path, "rev-parse", "HEAD").stdout.strip()


# --- unborn branch (a repo with zero commits) --------------------------------


@pytest.fixture()
def unborn_repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


def test_unborn_branch_has_no_commit(unborn_repo: Path) -> None:
    """`git init` alone produces a repo where HEAD points nowhere yet. A
    capsule must say so rather than report a placeholder commit."""
    facts = collect_git_facts(unborn_repo)
    assert facts["repo_root"] == str(unborn_repo.resolve())
    assert facts["commit"] is None
    assert facts["branch"] == "main"
    assert facts["detached"] is False
    assert facts["head_published"] is None
    assert facts["error"] is None


def test_unborn_branch_worktree_commit_is_not_a_fabricated_hash(unborn_repo: Path) -> None:
    """`git worktree list --porcelain` reports the all-zero object id for an
    unborn HEAD. That id names no real commit, so recording it verbatim would
    let a capsule claim a specific commit exists when nothing has been
    committed at all."""
    worktrees = project_from_facts(collect_git_facts(unborn_repo))["worktrees"]
    assert len(worktrees) == 1
    assert worktrees[0]["is_current"] is True
    assert worktrees[0]["commit"] is None


def test_unborn_branch_can_still_be_dirty(unborn_repo: Path) -> None:
    """Untracked files exist before the first commit; `dirty` should reflect
    that instead of requiring a commit to compare against."""
    (unborn_repo / "draft.txt").write_text("work in progress\n", encoding="utf-8")
    facts = collect_git_facts(unborn_repo)
    assert facts["dirty"] is True
    assert facts["changed_files_total"] == 1
    assert facts["changed_files"][0]["status"] == "untracked"


# --- detached HEAD -------------------------------------------------------


@pytest.fixture()
def detached_repo(tmp_path: Path) -> tuple[Path, str]:
    _init_repo(tmp_path)
    first = _commit(tmp_path, "a.txt", "one\n", "first")
    _commit(tmp_path, "a.txt", "two\n", "second")
    _git(tmp_path, "checkout", "-q", first)
    return tmp_path, first


def test_detached_head_has_a_commit_but_no_branch(detached_repo: tuple[Path, str]) -> None:
    repo, first = detached_repo
    facts = collect_git_facts(repo)
    assert facts["detached"] is True
    assert facts["branch"] is None
    assert facts["commit"] == first


def test_detached_head_worktree_matches_top_level_commit(detached_repo: tuple[Path, str]) -> None:
    repo, first = detached_repo
    worktrees = project_from_facts(collect_git_facts(repo))["worktrees"]
    assert worktrees[0]["commit"] == first
    assert worktrees[0]["branch"] is None


# --- publication status ---------------------------------------------------


def test_head_published_true_when_commit_is_on_a_remote(tmp_path: Path) -> None:
    """`head_published` must be able to say ``True``, not just ``False`` -
    otherwise a reader can never tell a pushed commit from a local one."""
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _init_repo(checkout)
    _commit(checkout, "a.txt", "content\n", "initial")
    _git(checkout, "remote", "add", "origin", str(bare))
    _git(checkout, "push", "-q", "origin", "main")

    facts = collect_git_facts(checkout)
    assert facts["head_published"] is True
    assert facts["remotes"] == [{"name": "origin", "url": str(bare)}]


def test_head_published_false_for_a_local_only_commit_on_top_of_a_remote(tmp_path: Path) -> None:
    """A repo can have a remote and still be unpublished if the newest commit
    hasn't been pushed - the two facts must not be conflated."""
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _init_repo(checkout)
    _commit(checkout, "a.txt", "content\n", "initial")
    _git(checkout, "remote", "add", "origin", str(bare))
    _git(checkout, "push", "-q", "origin", "main")
    _commit(checkout, "a.txt", "more\n", "unpushed")

    facts = collect_git_facts(checkout)
    assert facts["remotes"], "a remote must still be recorded"
    assert facts["head_published"] is False


def test_multiple_remotes_are_all_recorded(tmp_path: Path) -> None:
    """Only checking `remote.origin.url` would miss forks and mirrors added
    under other names."""
    repo = tmp_path
    _init_repo(repo)
    _commit(repo, "a.txt", "content\n", "initial")
    _git(repo, "remote", "add", "origin", "https://user:secret@example.test/org/repo.git")
    _git(repo, "remote", "add", "upstream", "git@example.test:org/upstream.git")

    facts = collect_git_facts(repo)
    remotes = {item["name"]: item["url"] for item in facts["remotes"]}
    assert remotes["origin"] == "https://example.test/org/repo.git"
    assert remotes["upstream"] == "example.test:org/upstream.git"
    assert "secret" not in str(facts["remotes"])


# --- truncation of a very dirty worktree ----------------------------------


def test_changed_files_list_is_capped_but_the_total_is_not(tmp_path: Path) -> None:
    """A worktree with hundreds of changed files must still report an
    accurate total, even though only a bounded sample is listed - otherwise a
    capped list would misrepresent a very dirty tree as a mostly clean one."""
    repo = tmp_path
    _init_repo(repo)
    _commit(repo, "a.txt", "content\n", "initial")
    file_count = DEFAULT_BOUNDS.max_recorded_changed_files + 15
    for index in range(file_count):
        (repo / f"untracked-{index}.txt").write_text("x", encoding="utf-8")

    facts = collect_git_facts(repo)
    assert len(facts["changed_files"]) == DEFAULT_BOUNDS.max_recorded_changed_files
    assert facts["changed_files_total"] == file_count
    assert facts["dirty"] is True


# --- symlinked paths -------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs elevated privileges on Windows")
def test_symlinked_untracked_file_is_not_hashed_or_marked_existing(tmp_path: Path) -> None:
    """Hashing through a symlink could read a file outside the repository.
    The recorded fact must make clear that nothing was verified for it,
    rather than silently hashing the link's target."""
    repo = tmp_path
    _init_repo(repo)
    _commit(repo, "real.txt", "hello\n", "initial")
    (repo / "link.txt").symlink_to(repo / "real.txt")

    facts = collect_git_facts(repo)
    entry = next(item for item in facts["changed_files"] if item["path"] == "link.txt")
    assert entry["status"] == "untracked"
    assert entry["hash"] is None
    assert entry["exists"] is False


# --- locations that are not inside a repository at all ---------------------


def test_find_repo_root_returns_none_outside_any_repository(tmp_path: Path) -> None:
    plain_directory = tmp_path / "not-a-repo"
    plain_directory.mkdir()
    assert find_repo_root(plain_directory) is None


def test_collect_git_facts_reports_an_error_outside_any_repository(tmp_path: Path) -> None:
    plain_directory = tmp_path / "not-a-repo"
    plain_directory.mkdir()
    facts = collect_git_facts(plain_directory)
    assert facts["repo_root"] is None
    assert facts["error"]
    assert facts["commit"] is None
    assert facts["changed_files"] == []


def test_find_repo_root_returns_none_for_a_path_that_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere" / "at-all"
    assert find_repo_root(missing) is None
