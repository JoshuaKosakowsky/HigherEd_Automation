"""Real local Git repositories verify update safety without credentials/network."""

import json
import os
from pathlib import Path
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
        version_file = self.source / 'app/gui/__init__.py'
        version_file.parent.mkdir(parents=True)
        version_file.write_text('APP_VERSION = "0.34.1"\n', encoding='utf-8')
        self.commit('Initial')
        self.git(self.root, 'clone', '--bare', str(self.source), str(self.remote))
        self.git(self.root, 'clone', str(self.remote), str(self.clone))
        self.git(self.source, 'remote', 'add', 'origin', str(self.remote))
        self.git(self.clone, 'config', 'user.name', 'Synthetic Test')
        self.git(self.clone, 'config', 'user.email', 'test@example.invalid')
        self.updater = RepositoryUpdater(self.clone)
        self.policy = self.root / 'policy.json'
        self.policy.write_text(json.dumps({
            'schemaVersion': 3,
            'metadata': {'ownerLogin': 'ADMIN'},
            'users': {
                'ADMIN': {'displayName': 'Test Administrator', 'jobTitle': 'Manager', 'view': 'administrator'},
                'STAFF': {'displayName': 'Test Staff', 'jobTitle': 'Analyst', 'view': 'analyst'},
            },
            'views': {'administrator': {'workflows': ['*']}, 'analyst': {'workflows': []}},
        }), encoding='utf-8')
        self.staff_updater = RepositoryUpdater(self.clone, access_config_path=self.policy)

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
        self.git(self.source, 'push', 'origin', 'HEAD')

    def publish_development(self):
        self.git(self.source, 'checkout', '-b', 'Development')
        self.git(self.source, 'push', 'origin', 'Development')

    def switch(self, branch, login='ADMIN'):
        with patch('app.gui.services.updates.get_current_login', return_value=login):
            plan = self.staff_updater.check_branch(branch)
            self.staff_updater.switch_branch(plan)
            return plan

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

    def test_staff_and_unavailable_access_cannot_switch_but_can_update(self):
        self.publish(text='stable release\n')
        self.publish_development()
        before = self.updater.installed_revision()
        with self.assertRaisesRegex(UpdateError, 'Only an administrator'):
            self.switch('Development', 'STAFF')
        self.policy.unlink()
        with self.assertRaisesRegex(UpdateError, 'Only an administrator'):
            self.switch('Development')
        self.assertEqual(self.updater.installed_revision(), before)
        self.assertEqual(self.git(self.clone, 'branch', '--list'), '* main')
        plan = self.staff_updater.check()
        self.staff_updater.install(plan)
        self.assertEqual((self.clone / 'app.txt').read_text(), 'stable release\n')

    def test_stable_installation_tests_development_and_returns_to_updated_main(self):
        self.publish(text='selector release\n')
        self.publish_development()
        (self.clone / 'settings.local').write_text('private value')
        staff_clone = self.root / 'staff'
        self.git(self.root, 'clone', '--branch', 'main', str(self.remote), str(staff_clone))
        stable = RepositoryUpdater(staff_clone)

        self.updater.install(self.updater.check())
        release = self.updater.installed_revision()
        self.assertEqual((self.clone / 'app.txt').read_text(), 'selector release\n')
        self.assertEqual(self.switch('Development').branch, 'Development')
        self.assertEqual(self.updater.installed_revision().commit, release.commit)

        self.publish('requirements.txt', 'synthetic==1.0\n')
        (self.source / 'app/gui/__init__.py').write_text('APP_VERSION = "0.34.2"\n', encoding='utf-8')
        self.publish(text='development-only fix\n')
        self.assertEqual(stable.check().commit_count, 0)
        plan = self.updater.check()
        self.assertEqual((plan.branch, plan.commit_count), ('Development', 2))
        self.assertTrue(plan.setup_required)
        self.updater.install(plan)
        development = self.updater.installed_revision()
        self.assertNotEqual(development.commit, release.commit)
        self.assertEqual((self.clone / 'app.txt').read_text(), 'development-only fix\n')

        self.git(self.source, 'checkout', 'main')
        self.publish(text='new stable release\n')
        stable_plan = self.switch('main')
        self.assertTrue(stable_plan.setup_required)
        self.assertEqual(stable_plan.version, '0.34.1')
        self.assertEqual(self.updater.installed_revision().branch, 'main')
        self.assertEqual((self.clone / 'app.txt').read_text(), 'new stable release\n')
        self.assertFalse((self.clone / 'requirements.txt').exists())
        self.assertEqual(self.git(self.clone, 'rev-parse', 'Development'), plan.target_commit)

        self.publish(text='ordinary stable update\n')
        self.updater.install(self.updater.check())
        self.assertEqual((self.clone / 'app.txt').read_text(), 'ordinary stable update\n')
        self.assertEqual((self.clone / 'settings.local').read_text(), 'private value')
        self.assertTrue(self.switch('Development').setup_required)
        self.assertEqual(self.updater.installed_revision(), development)

    def test_dirty_edits_untracked_files_and_source_local_commits_block_switch(self):
        self.publish_development()
        for filename in ('app.txt', 'untracked.txt'):
            with self.subTest(filename=filename):
                path = self.clone / filename
                path.write_text('local change')
                with self.assertRaisesRegex(UpdateError, 'local changes'):
                    self.switch('Development')
                self.assertEqual(path.read_text(), 'local change')
                if filename == 'app.txt':
                    self.git(self.clone, 'restore', filename)
                else:
                    path.unlink()
        self.git(self.clone, 'commit', '--allow-empty', '-m', 'Local commit on main')
        before = self.updater.installed_revision()
        with self.assertRaisesRegex(UpdateError, 'local commits'):
            self.switch('Development')
        self.assertEqual(self.updater.installed_revision(), before)

    def test_local_commits_on_destination_are_preserved(self):
        self.publish_development()
        self.git(self.clone, 'fetch', 'origin')
        self.git(self.clone, 'checkout', '-b', 'Development', '--track', 'origin/Development')
        self.git(self.clone, 'commit', '--allow-empty', '-m', 'Local commit on Development')
        local = self.git(self.clone, 'rev-parse', 'HEAD')
        self.git(self.clone, 'checkout', 'main')
        self.publish()
        with self.assertRaisesRegex(UpdateError, 'local commits'):
            self.switch('Development')
        self.assertEqual(self.updater.installed_revision().branch, 'main')
        self.assertEqual(self.git(self.clone, 'rev-parse', 'Development'), local)

    def test_switch_collision_preserves_ignored_settings_and_source_branch(self):
        self.publish_development()
        (self.source / 'settings.local').write_text('published setting')
        self.git(self.source, 'add', '-f', 'settings.local')
        self.git(self.source, 'commit', '-m', 'Synthetic ignored-file collision')
        self.git(self.source, 'push', 'origin', 'Development')
        (self.clone / 'settings.local').write_text('private value')
        before = self.updater.installed_revision()
        with self.assertRaisesRegex(UpdateError, 'conflicting local files') as caught:
            self.switch('Development')
        self.assertTrue(caught.exception.restart_required)
        self.assertEqual(self.updater.installed_revision(), before)
        self.assertEqual((self.clone / 'settings.local').read_text(), 'private value')

    def test_switch_to_unpublished_branch_leaves_installation_usable(self):
        before = self.updater.installed_revision()
        with self.assertRaisesRegex(UpdateError, 'Could not reach') as caught:
            self.switch('Development')
        self.assertFalse(caught.exception.restart_required)
        self.assertEqual(self.updater.installed_revision(), before)
        self.assertEqual(self.updater.check().commit_count, 0)

    def test_single_branch_clone_can_track_and_update_both_branches(self):
        narrow_clone = self.root / 'narrow'
        self.git(self.root, 'clone', '--single-branch', str(self.remote), str(narrow_clone))
        self.staff_updater = RepositoryUpdater(narrow_clone, access_config_path=self.policy)
        self.publish_development()
        self.switch('Development')
        self.publish()
        self.staff_updater.install(self.staff_updater.check())
        self.assertEqual((narrow_clone / 'app.txt').read_text(), 'updated\n')
        self.switch('main')
        self.assertEqual((narrow_clone / 'app.txt').read_text(), 'initial\n')

    def test_development_preview_refuses_older_release_and_can_be_retried(self):
        self.publish_development()
        self.git(self.source, 'checkout', 'main')
        self.publish('app/gui/__init__.py', 'APP_VERSION = "0.34.2"\n')
        self.updater.install(self.updater.check())
        before = self.updater.installed_revision()
        with patch('app.gui.services.updates.get_current_login', return_value='ADMIN'):
            with self.assertRaisesRegex(UpdateError, 'Development offers older version 0.34.1') as caught:
                self.staff_updater.check_branch('Development')
            self.assertFalse(caught.exception.restart_required)
            self.assertEqual(self.updater.installed_revision(), before)
            self.assertEqual(self.git(self.clone, 'branch', '--list'), '* main')
            self.git(self.source, 'push', 'origin', 'main:Development')
            plan = self.staff_updater.check_branch('Development')
            self.assertEqual(plan.version, '0.34.2')
            self.assertEqual(self.updater.installed_revision(), before)
            self.staff_updater.switch_branch(plan)
        self.assertEqual(self.updater.installed_revision().branch, 'Development')

    def test_branch_install_rejects_target_changed_after_preview(self):
        self.publish_development()
        with patch('app.gui.services.updates.get_current_login', return_value='ADMIN'):
            plan = self.staff_updater.check_branch('Development')
            self.publish()
            self.staff_updater.check_branch('Development')
            with self.assertRaisesRegex(UpdateError, 'update source changed'):
                self.staff_updater.switch_branch(plan)
        self.assertEqual(self.git(self.clone, 'branch', '--list'), '* main')

    def test_access_revoked_during_fetch_prevents_checkout(self):
        self.publish_development()
        fetch = self.staff_updater._fetch

        def fetch_then_remove_policy(*args):
            fetch(*args)
            self.policy.unlink(missing_ok=True)

        with patch.object(self.staff_updater, '_fetch', side_effect=fetch_then_remove_policy):
            with self.assertRaisesRegex(UpdateError, 'Only an administrator'):
                self.switch('Development')
        self.assertEqual(self.git(self.clone, 'branch', '--list'), '* main')


if __name__ == '__main__':
    unittest.main()
