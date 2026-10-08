"""Real local Git repositories verify update safety without credentials/network."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.gui.services.updates import RepositoryUpdater, UpdateError


@unittest.skipUnless(shutil.which('git'), 'Git is required for local integration tests')
class RepositoryUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.remote = self.root / 'remote.git'
        self.clone = self.root / 'installation'
        self.source.mkdir()
        self.git(self.source, 'init', '-b', 'main')
        self.git(self.source, 'config', 'user.name', 'Synthetic Test')
        self.git(self.source, 'config', 'user.email', 'test@example.invalid')
        (self.source / '.gitignore').write_text('settings.local\n', encoding='utf-8')
        (self.source / 'app.txt').write_text('initial\n', encoding='utf-8')
        self.commit('Initial')
        self.git(self.root, 'clone', '--bare', str(self.source), str(self.remote))
        self.git(self.root, 'clone', str(self.remote), str(self.clone))
        self.git(self.source, 'remote', 'add', 'origin', str(self.remote))
        self.git(self.clone, 'config', 'user.name', 'Synthetic Test')
        self.git(self.clone, 'config', 'user.email', 'test@example.invalid')
        self.updater = RepositoryUpdater(self.clone)

    def git(self, cwd, *args):
        environment = os.environ.copy()
        environment.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        result = subprocess.run(['git', *args], cwd=cwd, env=environment,
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def commit(self, message):
        self.git(self.source, 'add', '.')
        self.git(self.source, 'commit', '-m', message)

    def publish(self, filename='app.txt', text='updated\n'):
        (self.source / filename).write_text(text, encoding='utf-8')
        self.commit('Update')
        self.git(self.source, 'push', 'origin', 'main')

    def test_check_does_not_install_and_install_preserves_ignored_settings(self):
        self.publish()
        (self.clone / 'settings.local').write_text('private synthetic setting')
        plan = self.updater.check()
        self.assertEqual(plan.commit_count, 1)
        self.assertEqual((self.clone / 'app.txt').read_text(), 'initial\n')
        self.updater.install(plan)
        self.assertEqual((self.clone / 'app.txt').read_text(), 'updated\n')
        self.assertEqual((self.clone / 'settings.local').read_text(), 'private synthetic setting')
        self.assertEqual(self.updater.check().commit_count, 0)

    def test_dirty_tracked_and_untracked_files_block_updates(self):
        for filename in ('app.txt', 'untracked.txt'):
            with self.subTest(filename=filename):
                path = self.clone / filename
                path.write_text('local change')
                with self.assertRaisesRegex(UpdateError, 'local changes'):
                    self.updater.check()
                if filename == 'app.txt':
                    self.git(self.clone, 'restore', filename)
                else:
                    path.unlink()

    def test_local_commits_and_divergence_are_refused(self):
        (self.clone / 'app.txt').write_text('local commit')
        self.git(self.clone, 'add', '.')
        self.git(self.clone, 'commit', '-m', 'Local change')
        with self.assertRaisesRegex(UpdateError, 'local commits'):
            self.updater.check()
        self.publish()
        with self.assertRaisesRegex(UpdateError, 'local commits'):
            self.updater.check()

    def test_missing_tracking_and_detached_head_are_refused(self):
        self.git(self.clone, 'branch', '--unset-upstream')
        with self.assertRaisesRegex(UpdateError, 'No update source'):
            self.updater.check()
        self.git(self.clone, 'checkout', '--detach')
        with self.assertRaisesRegex(UpdateError, 'not on a branch'):
            self.updater.check()

    def test_non_clone_and_nested_folder_are_refused(self):
        with self.assertRaisesRegex(UpdateError, 'not a Git clone'):
            RepositoryUpdater(self.root).check()
        nested = self.clone / 'nested'
        nested.mkdir()
        with self.assertRaisesRegex(UpdateError, 'root of its own'):
            RepositoryUpdater(nested).check()

    def test_setup_changes_are_identified(self):
        self.publish('requirements.txt', 'synthetic==1.0\n')
        self.assertTrue(self.updater.check().setup_required)

    def test_install_rechecks_local_changes_branch_and_target(self):
        self.publish()
        plan = self.updater.check()
        (self.clone / 'app.txt').write_text('late local edit')
        with self.assertRaisesRegex(UpdateError, 'local changes'):
            self.updater.install(plan)
        self.git(self.clone, 'restore', 'app.txt')
        self.git(self.clone, 'checkout', '-b', 'other', '--track', 'origin/main')
        with self.assertRaisesRegex(UpdateError, 'changed'):
            self.updater.install(plan)
        self.git(self.clone, 'checkout', 'main')
        self.publish(text='second update\n')
        self.updater.check()
        with self.assertRaisesRegex(UpdateError, 'changed'):
            self.updater.install(plan)

    def test_ignored_file_collision_does_not_overwrite_private_file(self):
        (self.source / 'settings.local').write_text('published file')
        self.git(self.source, 'add', '-f', 'settings.local')
        self.git(self.source, 'commit', '-m', 'Synthetic collision')
        self.git(self.source, 'push', 'origin', 'main')
        (self.clone / 'settings.local').write_text('private value')
        plan = self.updater.check()
        with self.assertRaises(UpdateError) as caught:
            self.updater.install(plan)
        self.assertTrue(caught.exception.restart_required)
        self.assertEqual((self.clone / 'settings.local').read_text(), 'private value')
        self.assertEqual(self.git(self.clone, 'rev-parse', 'HEAD'), plan.current_commit)

    def test_unfinished_git_operation_is_refused(self):
        (self.clone / '.git' / 'rebase-merge').mkdir()
        with self.assertRaisesRegex(UpdateError, 'unfinished'):
            self.updater.check()

    def test_deleted_remote_branch_cannot_look_up_to_date(self):
        self.git(self.remote, 'update-ref', '-d', 'refs/heads/main')
        with self.assertRaisesRegex(UpdateError, 'Could not reach'):
            self.updater.check()

    def test_network_failure_does_not_install(self):
        self.git(self.clone, 'remote', 'set-url', 'origin', str(self.root / 'missing.git'))
        before = self.git(self.clone, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(UpdateError, 'Could not reach'):
            self.updater.check()
        self.assertEqual(self.git(self.clone, 'rev-parse', 'HEAD'), before)

    def test_missing_git_and_timeout_have_staff_safe_errors(self):
        with patch('app.gui.services.updates.shutil.which', return_value=None):
            with self.assertRaisesRegex(UpdateError, 'Git is not installed'):
                self.updater.check()
        with patch('app.gui.services.updates.subprocess.run', side_effect=subprocess.TimeoutExpired('git', 120)):
            with self.assertRaisesRegex(UpdateError, 'timed out'):
                self.updater.check()


if __name__ == '__main__':
    unittest.main()
