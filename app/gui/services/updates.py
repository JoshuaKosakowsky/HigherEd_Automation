"""Git updates and administrator branch switches, independent of Qt."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess

from app.gui.services.access import (
    AccessConfigurationError, get_current_login, load_access_configuration,
)

UPDATE_BRANCHES = ("main", "Development")


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


@dataclass(frozen=True)
class InstalledRevision:
    branch: str
    commit: str


@dataclass(frozen=True)
class BranchSwitchResult:
    branch: str
    setup_required: bool


class RepositoryUpdater:
    """Check, fast-forward, or explicitly switch the installed Git branch."""

    def __init__(self, root: Path, *, access_config_path: Path | None = None) -> None:
        self.root = root.resolve()
        self.access_config_path = access_config_path

    def can_switch_branch(self) -> bool:
        if self.access_config_path is None:
            return False
        try:
            policy = load_access_configuration(self.access_config_path)
        except (AccessConfigurationError, OSError):
            return False
        return policy.is_administrator(get_current_login())

    def _require_switch_authorization(self) -> None:
        if not self.can_switch_branch():
            raise UpdateError("Only an administrator can switch the update branch. Check that staff access settings are available.")

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

    def _require_clone_root(self) -> None:
        top = self._git("rev-parse", "--show-toplevel", message=(
            "This folder is not a Git clone. Ask your administrator to provision a clone with repository access."
        ))
        if Path(top).resolve() != self.root:
            raise UpdateError("The app must run from the root of its own Git clone.")

    def installed_revision(self) -> InstalledRevision:
        self._require_clone_root()
        return InstalledRevision(
            self._git("rev-parse", "--abbrev-ref", "HEAD"),
            self._git("rev-parse", "--short=12", "HEAD"),
        )

    def _state(self) -> tuple[str, str, str, str]:
        self._require_clone_root()
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

    def _fetch(self, remote: str, remote_branch: str, upstream: str) -> None:
        # Fetch the exact branch so a deleted remote branch cannot appear up to
        # date merely because an old tracking ref still exists locally.
        self._git("fetch", "--no-tags", "--no-recurse-submodules", remote,
                  f"+{remote_branch}:{upstream}", message=(
            "Could not reach the update source. Check network/VPN access or ask IT to verify Git authentication and repository access."
        ))

    def _setup_required(self, current: str, target: str) -> bool:
        changed = self._git("diff", "--no-renames", "--name-only", current, target).splitlines()
        return any(
            path in {"requirements.txt", "setup.ps1"} or path.startswith(("setup/", "powershell/", "launcher/"))
            for path in changed
        )

    def check(self) -> UpdatePlan:
        before = self._state()
        remote_branch = self._git("config", "--get", f"branch.{before[0]}.merge")
        if not remote_branch.startswith("refs/heads/") or not before[2].startswith("refs/remotes/"):
            raise UpdateError("The update source must be a remote tracking branch.")
        self._fetch(before[1], remote_branch, before[2])
        branch, remote, upstream, current = self._state()
        if before != (branch, remote, upstream, current):
            raise UpdateError("The installation changed during the check. Check for updates again.")
        target = self._git("rev-parse", upstream)
        ahead, behind = map(int, self._git("rev-list", "--left-right", "--count", f"{current}...{target}").split())
        if ahead:
            raise UpdateError("This installation has local commits or differs from the update source. Ask your administrator to resolve it; automatic updates cannot merge or discard commits.")
        return UpdatePlan(self.root, branch, remote, upstream, current, target, behind,
                          self._setup_required(current, target))

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

    def switch_branch(self, target_branch: str) -> BranchSwitchResult:
        self._require_switch_authorization()
        if target_branch not in UPDATE_BRANCHES:
            raise UpdateError("Choose main or Development as the update branch.")
        before = self._state()
        branch, remote, upstream, current = before
        if branch == target_branch:
            raise UpdateError(f"This installation already follows {target_branch}.")
        if (branch not in UPDATE_BRANCHES or upstream != f"refs/remotes/{remote}/{branch}"
                or self._git("config", "--get", f"branch.{branch}.merge") != f"refs/heads/{branch}"):
            raise UpdateError("Switching requires main or Development to track its matching remote branch.")

        self._fetch(remote, f"refs/heads/{branch}", upstream)
        self._git("merge-base", "--is-ancestor", current, upstream, message=(
            "The current branch has local commits or differs from its update source. Review it before switching."
        ))
        target_ref = f"refs/heads/{target_branch}"
        target_upstream = f"refs/remotes/{remote}/{target_branch}"
        self._fetch(remote, target_ref, target_upstream)
        target = self._git("rev-parse", target_upstream)
        setup_required = self._setup_required(current, target)
        local_target = self._git("for-each-ref", "--format=%(refname) %(upstream)", target_ref).splitlines()
        existing_target = any(entry.split()[0] == target_ref for entry in local_target)
        if existing_target and f"{target_ref} {target_upstream}" not in local_target:
            raise UpdateError(f"The local {target_branch} branch must track {remote}/{target_branch} before switching.")

        if self._state() != before or self._git("rev-parse", target_upstream) != target:
            raise UpdateError("The installation or update source changed. Try switching again.")
        self._require_switch_authorization()
        if existing_target:
            # Advance the inactive branch without resetting it or checking out
            # an intermediate revision. Git rejects divergence and worktree use.
            self._git("fetch", "--no-tags", "--no-recurse-submodules", ".", f"{target}:{target_ref}", message=(
                f"Could not advance the local {target_branch} branch. Review it for local commits or use in another worktree."
            ))
            checkout = (target_branch,)
        else:
            fetch_specs = self._git("config", "--get-all", f"remote.{remote}.fetch").splitlines()
            if not {spec.lstrip("+") for spec in fetch_specs}.intersection({
                f"{target_ref}:{target_upstream}", f"refs/heads/*:refs/remotes/{remote}/*",
            }):
                # A single-branch clone needs one additional tracking refspec.
                self._git("remote", "set-branches", "--add", remote, target_branch, message=(
                    f"Could not configure updates from {remote}/{target_branch}."
                ))
            checkout = ("-b", target_branch, "--track", target_upstream)
        try:
            self._git("checkout", "--no-overwrite-ignore", *checkout, message=(
                f"Git could not switch to {target_branch}. Close other automation tools and check for file locks or conflicting local files."
            ))
            if self._state() != (target_branch, remote, target_upstream, target):
                raise UpdateError("The installation changed while switching branches. Ask your administrator to inspect it.")
        except UpdateError as error:
            raise UpdateError(f"{error} Close and reopen the app before using workflows.", restart_required=True) from None
        return BranchSwitchResult(target_branch, setup_required)
