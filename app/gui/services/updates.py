"""Conservative Git updates for an installed repository; independent of Qt."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


class UpdateError(RuntimeError):
    def __init__(self, message: str, *, restart_required: bool = False) -> None:
        super().__init__(message)
        self.restart_required = restart_required


@dataclass(frozen=True)
class UpdatePlan:
    root: Path
    branch: str
    remote: str
    upstream: str
    current_commit: str
    target_commit: str
    commit_count: int
    setup_required: bool


class RepositoryUpdater:
    """Fetch only during checks; install the reviewed commit with a fast-forward."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _git(self, *arguments: str, message: str = "Git could not inspect this installation.") -> str:
        executable = shutil.which("git")
        if not executable:
            raise UpdateError("Git is not installed or is unavailable to the app. Ask IT to install Git and reopen the app.")
        environment = os.environ.copy()
        environment.update({
            "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never",
            "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=15",
            "GIT_ASKPASS": "", "SSH_ASKPASS": "",
        })
        try:
            result = subprocess.run(
                [executable, "-c", f"core.hooksPath={os.devnull}", *arguments],
                cwd=self.root, env=environment, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, errors="replace", timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            raise UpdateError("The Git operation timed out. Check your connection and try again.") from None
        except OSError:
            raise UpdateError(message) from None
        if result.returncode:
            # Git diagnostics can contain credential-bearing URLs and private
            # filenames. Neither display nor log raw command output.
            raise UpdateError(message)
        return result.stdout.strip()

    def _state(self) -> tuple[str, str, str, str]:
        top = self._git("rev-parse", "--show-toplevel", message=(
            "This folder is not a Git clone. Ask your administrator to provision a clone with repository access."
        ))
        if Path(top).resolve() != self.root:
            raise UpdateError("The app must run from the root of its own Git clone.")
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "index.lock"):
            location = Path(self._git("rev-parse", "--git-path", marker))
            if not location.is_absolute():
                location = self.root / location
            if location.exists():
                raise UpdateError("Another Git operation is unfinished. Ask your administrator to resolve it before updating.")
        if self._git("status", "--porcelain", "--untracked-files=all"):
            raise UpdateError("This installation has local changes or untracked files. Ask your administrator to review them before updating.")
        branch = self._git("symbolic-ref", "--quiet", "--short", "HEAD", message=(
            "This installation is not on a branch. Ask your administrator to configure its update branch."
        ))
        remote = self._git("config", "--get", f"branch.{branch}.remote", message=(
            "No update source is configured. Ask your administrator to configure a tracking branch."
        ))
        if remote == "." or remote.startswith("-"):
            raise UpdateError("The update branch must track a configured remote repository.")
        upstream = self._git("rev-parse", "--symbolic-full-name", "@{upstream}", message=(
            "No update source is configured. Ask your administrator to configure a tracking branch."
        ))
        return branch, remote, upstream, self._git("rev-parse", "HEAD")

    def check(self) -> UpdatePlan:
        before = self._state()
        remote_branch = self._git("config", "--get", f"branch.{before[0]}.merge")
        if not remote_branch.startswith("refs/heads/") or not before[2].startswith("refs/remotes/"):
            raise UpdateError("The update source must be a remote tracking branch.")
        # Fetch the exact branch so a deleted remote branch cannot appear up to
        # date merely because an old tracking ref still exists locally.
        self._git("fetch", "--no-tags", "--no-recurse-submodules", before[1],
                  f"+{remote_branch}:{before[2]}", message=(
            "Could not reach the update source. Check network/VPN access or ask IT to verify Git authentication and repository access."
        ))
        branch, remote, upstream, current = self._state()
        if before != (branch, remote, upstream, current):
            raise UpdateError("The installation changed during the check. Check for updates again.")
        target = self._git("rev-parse", upstream)
        ahead, behind = map(int, self._git("rev-list", "--left-right", "--count", f"{current}...{target}").split())
        if ahead:
            raise UpdateError("This installation has local commits or differs from the update source. Ask your administrator to resolve it; automatic updates cannot merge or discard commits.")
        changed = self._git("diff", "--name-only", current, target).splitlines()
        setup_required = any(
            path in {"requirements.txt", "setup.ps1"} or path.startswith(("setup/", "powershell/", "launcher/"))
            for path in changed
        )
        return UpdatePlan(self.root, branch, remote, upstream, current, target, behind, setup_required)

    def install(self, plan: UpdatePlan) -> None:
        if plan.root != self.root or self._state() != (
            plan.branch, plan.remote, plan.upstream, plan.current_commit,
        ) or self._git("rev-parse", plan.upstream) != plan.target_commit:
            raise UpdateError("The installation or update source changed. Check for updates again.")
        if not plan.commit_count:
            return
        self._git("merge-base", "--is-ancestor", plan.current_commit, plan.target_commit,
                  message="The update cannot be installed as a fast-forward. Check for updates again.")
        try:
            # Even ignored credentials/data must not be overwritten if a future
            # commit introduces a tracked file at the same path.
            self._git("merge", "--ff-only", "--no-overwrite-ignore", "--no-edit", plan.target_commit,
                      message="Git could not install the update. Close other automation tools and ask your administrator to check file locks or conflicting local files.")
            if self._git("rev-parse", "HEAD") != plan.target_commit:
                raise UpdateError("The installation changed while updating. Ask your administrator to inspect it.")
        except UpdateError as error:
            raise UpdateError(f"{error} Close and reopen the app before using workflows.", restart_required=True) from None
