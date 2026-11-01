#!/usr/bin/env python3
"""Tests for secret-sync."""

import unittest
import json
import os
import shutil
import stat
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import sync


class TestSecretSync(unittest.TestCase):
    """Test secret-sync functionality."""

    def setUp(self):
        """Create temporary files for testing."""
        self.temp_dir = Path.cwd() / (".scratch-" + uuid.uuid4().hex)
        self.temp_dir.mkdir()

        # Create config file
        self.config = {
            "secrets": ["API_KEY", "DB_PASSWORD"],
            "destination": str(self.temp_dir / ".env")
        }
        self.config_path = self.temp_dir / "config.json"
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f)

        # Create source secrets file
        self.source_secrets = {
            "API_KEY": "secret-api-key-123",
            "DB_PASSWORD": "super-secret-password",
            "OTHER_SECRET": "should-not-sync"
        }
        self.source_path = self.temp_dir / "secrets.json"
        with open(self.source_path, 'w') as f:
            json.dump(self.source_secrets, f)

    def tearDown(self):
        """Remove the test fixture directory from the workspace."""
        shutil.rmtree(self.temp_dir)

    def test_load_config(self):
        """Test loading configuration."""
        config = sync.load_config(self.config_path)
        self.assertIn('secrets', config)
        self.assertIn('destination', config)

    def test_load_config_accepts_utf8_bom(self):
        """Test loading config saved with a Windows UTF-8 BOM."""
        self.config_path.write_bytes(b'\xef\xbb\xbf' + json.dumps(self.config).encode('utf-8'))
        config = sync.load_config(self.config_path)
        self.assertEqual(config['secrets'], ['API_KEY', 'DB_PASSWORD'])

    def test_load_config_rejects_invalid_utf8(self):
        """Test invalid config encoding is reported without a traceback."""
        self.config_path.write_bytes(b'\xff')
        with self.assertRaises(SystemExit):
            sync.load_config(self.config_path)

    def test_validate_config_valid(self):
        """Test validation of valid config."""
        config = {"secrets": ["KEY1"], "destination": str(self.temp_dir / "output.env")}
        sync.validate_config(config)

    def test_validate_config_rejects_empty_allowlist(self):
        """Test validation rejects a config that cannot select any secret."""
        with self.assertRaises(SystemExit):
            sync.validate_config({"secrets": [], "destination": ".env"})

    def test_validate_aws_destination(self):
        """Test validation of an AWS Secrets Manager destination."""
        sync.validate_config({
            "secrets": ["KEY1"],
            "destination": {"type": "aws-secrets-manager", "name": "app/config"},
        })

    def test_validate_config_rejects_invalid_secret_names(self):
        """Test validation rejects empty and non-string secret names."""
        with self.assertRaises(SystemExit):
            sync.validate_config({"secrets": ["KEY1", ""], "destination": ".env"})
        with self.assertRaises(SystemExit):
            sync.validate_config({"secrets": ["KEY1", 2], "destination": ".env"})

    def test_validate_config_rejects_names_that_break_dotenv_output(self):
        """Test names are safe for dotenv and secret-run environment output."""
        for name in ("1KEY", "KEY-NAME", "KEY NAME", "KEY=VALUE", "KEY\nINJECTED"):
            with self.subTest(name=name):
                with self.assertRaises(SystemExit):
                    sync.validate_config({"secrets": [name], "destination": ".env"})

    def test_validate_config_missing_secrets(self):
        """Test validation fails with missing secrets key."""
        config = {"destination": "/tmp/test"}
        with self.assertRaises(SystemExit):
            sync.validate_config(config)

    def test_validate_config_missing_destination(self):
        """Test validation fails with missing destination key."""
        config = {"secrets": ["KEY1"]}
        with self.assertRaises(SystemExit):
            sync.validate_config(config)

    def test_load_secrets_from_json(self):
        """Test loading secrets from JSON file."""
        secrets = sync.load_secrets_from_file(self.source_path)
        self.assertIn('API_KEY', secrets)
        self.assertEqual(secrets['API_KEY'], 'secret-api-key-123')

    def test_load_secrets_from_json_accepts_utf8_bom(self):
        """Test loading JSON secrets saved with a Windows UTF-8 BOM."""
        self.source_path.write_bytes(b'\xef\xbb\xbf' + json.dumps(self.source_secrets).encode('utf-8'))
        secrets = sync.load_secrets_from_file(self.source_path)
        self.assertEqual(secrets['API_KEY'], 'secret-api-key-123')

    def test_load_secrets_from_file_rejects_invalid_utf8(self):
        """Test invalid source encoding is reported without a traceback."""
        self.source_path.write_bytes(b'\xff')
        with self.assertRaisesRegex(sync.SyncError, 'could not decode source'):
            sync.load_secrets_from_file(self.source_path)

    def test_load_secrets_from_env_variant(self):
        """Test loading a conventional .env.production file."""
        source = self.temp_dir / '.env.production'
        source.write_text('export API_KEY="key 123" # inline comment\nDB_PASSWORD=pass456 # comment\n')
        self.assertEqual(
            sync.load_secrets_from_file(source),
            {"API_KEY": "key 123", "DB_PASSWORD": "pass456"},
        )

    def test_format_env_entry(self):
        """Test formatting environment variable entry."""
        entry = sync.format_env_entry('TEST_KEY', 'test_value')
        self.assertEqual(entry, 'TEST_KEY="test_value"')

    def test_format_env_entry_with_quotes(self):
        """Test formatting with quotes in value."""
        entry = sync.format_env_entry('KEY', 'value"with"quotes')
        self.assertIn('\\"', entry)

    def test_format_env_entry_escapes_newlines(self):
        """Test formatting keeps multiline values on one dotenv line."""
        self.assertEqual(sync.format_env_entry('KEY', 'line1\nline2'),
                         'KEY="line1\\nline2"')

    def test_generate_env_file(self):
        """Test generating env file with actual secrets."""
        secrets = {'API_KEY': 'key123', 'DB_PASSWORD': 'pass456'}
        output = self.temp_dir / '.env'
        sync.generate_env_file(secrets, ['API_KEY', 'DB_PASSWORD'], output, dry_run=False)

        self.assertTrue(output.exists())
        content = output.read_text()
        self.assertIn('API_KEY=', content)
        self.assertIn('DB_PASSWORD=', content)
        self.assertIn('key123', content)
        self.assertIn('pass456', content)

    def test_generate_env_file_dry_run(self):
        """Test dry run doesn't write file."""
        secrets = {'API_KEY': 'key123'}
        output = self.temp_dir / '.env.dry'
        sync.generate_env_file(secrets, ['API_KEY'], output, dry_run=True)

        self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX file modes are not portable to this platform")
    def test_generated_secret_file_is_owner_only(self):
        """Test generated secret files are not group- or world-readable."""
        output = self.temp_dir / '.env.private'
        sync.generate_env_file({'API_KEY': 'key123'}, ['API_KEY'], output)

        self.assertEqual(
            stat.S_IMODE(output.stat().st_mode),
            stat.S_IRUSR | stat.S_IWUSR,
        )

    def test_destination_write_failure_is_reported_as_sync_error(self):
        """Test a directory destination produces a user-facing sync error."""
        with self.assertRaisesRegex(sync.SyncError, 'could not write destination'):
            sync.generate_env_file(
                {'API_KEY': 'key123'}, ['API_KEY'], self.temp_dir,
            )

    def test_destination_encoding_failure_is_reported_as_sync_error(self):
        """Test an unencodable value does not escape as a Unicode traceback."""
        with self.assertRaisesRegex(sync.SyncError, 'could not write destination'):
            sync.generate_env_file(
                {'API_KEY': '\ud800'}, ['API_KEY'], self.temp_dir / '.env.bad',
            )

    def test_generate_stub_file(self):
        """Test generating stub file."""
        output = self.temp_dir / '.env.stub'
        sync.generate_stub_file(['API_KEY', 'DB_PASSWORD'], output, dry_run=False)

        self.assertTrue(output.exists())
        content = output.read_text()
        self.assertIn('CHANGE_ME', content)
        self.assertNotIn('secret-api-key', content)
        self.assertIn('API_KEY=', content)

    def test_generate_stub_file_dry_run(self):
        """Test stub dry run doesn't write file."""
        output = self.temp_dir / '.env.stub'
        sync.generate_stub_file(['API_KEY'], output, dry_run=True)

        self.assertFalse(output.exists())

    def test_main_runs_local_source_sync(self):
        """Test the CLI entry point completes a local source sync."""
        destination = self.temp_dir / '.env.from-main'
        config = self.temp_dir / 'main-config.json'
        config.write_text(json.dumps({
            'secrets': ['API_KEY'],
            'destination': str(destination),
        }))
        source = self.temp_dir / 'main-secrets.json'
        source.write_text(json.dumps({'API_KEY': 'key123', 'OTHER': 'ignored'}))

        self.assertEqual(sync.main([str(config), '--source', str(source)]), 0)
        self.assertEqual(destination.read_text(), 'API_KEY="key123"\n')

    def test_only_approved_secrets_sync(self):
        """Test that only approved secrets are synced."""
        secrets = {
            'APPROVED_1': 'value1',
            'APPROVED_2': 'value2',
            'NOT_APPROVED': 'should_not_appear'
        }
        output = self.temp_dir / '.env.filtered'
        sync.generate_env_file(secrets, ['APPROVED_1', 'APPROVED_2'], output, dry_run=False)

        content = output.read_text()
        self.assertIn('APPROVED_1', content)
        self.assertIn('APPROVED_2', content)
        self.assertNotIn('NOT_APPROVED', content)

    def test_load_secrets_from_environment(self):
        """Test reading only the approved names from a secret-run environment."""
        with patch.dict('os.environ', {'API_KEY': 'key123', 'OTHER': 'do-not-read'}, clear=True):
            self.assertEqual(sync.load_secrets_from_environment(['API_KEY']),
                             {'API_KEY': 'key123'})

    def test_load_secrets_from_environment_requires_each_name(self):
        """Test a missing injected secret fails without writing anything."""
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(sync.SyncError):
                sync.load_secrets_from_environment(['API_KEY'])

    def test_aws_dry_run_does_not_call_cli(self):
        """Test AWS dry-run reports names without invoking AWS CLI."""
        runner = unittest.mock.Mock()
        sync.sync_to_aws(
            {'API_KEY': 'key123'}, ['API_KEY'], 'app/config', dry_run=True,
            runner=runner,
        )
        runner.assert_not_called()

    def test_aws_sync_creates_missing_secret(self):
        """Test AWS sync creates a secret when describe reports it missing."""
        runner = unittest.mock.Mock(side_effect=[
            SimpleNamespace(returncode=1, stderr='ResourceNotFoundException', stdout=''),
            SimpleNamespace(returncode=0, stderr='', stdout=''),
        ])
        sync.sync_to_aws(
            {'API_KEY': 'key123'}, ['API_KEY'], 'app/config', runner=runner,
        )
        describe, create = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(describe[:3], ['aws', 'secretsmanager', 'describe-secret'])
        self.assertIn('create-secret', create)
        payload_reference = create[create.index('--secret-string') + 1]
        self.assertTrue(payload_reference.startswith('file://'))
        self.assertFalse(payload_reference.endswith('{"API_KEY":"key123"}'))

    def test_aws_sync_does_not_put_secret_value_in_cli_arguments(self):
        """Test AWS payloads are supplied through a temporary file, not argv."""
        commands = []
        payload_paths = []

        def runner(command, **kwargs):
            commands.append(command)
            if '--secret-string' in command:
                payload_reference = command[command.index('--secret-string') + 1]
                self.assertTrue(payload_reference.startswith('file://'))
                payload_path = Path(payload_reference[len('file://'):])
                payload_paths.append(payload_path)
                self.assertTrue(payload_path.exists())
                self.assertEqual(json.loads(payload_path.read_text()), {'API_KEY': 'key123'})
                self.assertNotIn('key123', ' '.join(command))
            return SimpleNamespace(returncode=0, stderr='', stdout='')

        sync.sync_to_aws(
            {'API_KEY': 'key123'}, ['API_KEY'], 'app/config', runner=runner,
        )

        self.assertEqual(len(commands), 2)
        self.assertEqual(len(payload_paths), 1)
        self.assertFalse(payload_paths[0].exists())

    def test_aws_sync_updates_existing_secret(self):
        """Test AWS sync updates an existing secret with the selected values."""
        runner = unittest.mock.Mock(side_effect=[
            SimpleNamespace(returncode=0, stderr='', stdout=''),
            SimpleNamespace(returncode=0, stderr='', stdout=''),
        ])
        sync.sync_to_aws(
            {'API_KEY': 'key123', 'OTHER': 'ignored'}, ['API_KEY'], 'app/config',
            runner=runner,
        )
        update = runner.call_args_list[1].args[0]
        self.assertIn('put-secret-value', update)
        payload_reference = update[update.index('--secret-string') + 1]
        self.assertTrue(payload_reference.startswith('file://'))
        self.assertNotIn('key123', ' '.join(update))

    def test_aws_missing_cli_has_clear_error(self):
        """Test a missing optional AWS CLI reports an actionable error."""
        runner = unittest.mock.Mock(side_effect=FileNotFoundError())
        with self.assertRaisesRegex(sync.SyncError, 'AWS CLI was not found'):
            sync.sync_to_aws(
                {'API_KEY': 'key123'}, ['API_KEY'], 'app/config', runner=runner,
            )

    def test_secret_run_role_dispatch_does_not_include_values(self):
        """Test role dispatch delegates to secret-run without exposing values."""
        result = SimpleNamespace(returncode=0)
        with patch.object(sync.subprocess, 'run', return_value=result) as runner:
            exit_code = sync.run_secret_run_role(
                'production', self.config_path, dry_run=True,
                secret_run_command='secret-run',
            )
        self.assertEqual(exit_code, 0)
        command = runner.call_args.args[0]
        self.assertIn('--source-env', command)
        self.assertNotIn('secret-api-key-123', command)
        self.assertNotIn('super-secret-password', command)

    def test_secret_run_role_failure_returns_exit_code(self):
        """Test a failed secret-run child is reported to the caller."""
        with patch.object(sync.subprocess, 'run', return_value=SimpleNamespace(returncode=7)):
            self.assertEqual(
                sync.run_secret_run_role(
                    'production', self.config_path,
                    secret_run_command='secret-run',
                ),
                7,
            )

    def test_secret_run_role_launch_failure_returns_exit_code(self):
        """Test an OS-level secret-run launch failure is reported, not raised."""
        def failing_runner(command, **kwargs):
            raise OSError('launch failed')

        self.assertEqual(
            sync.run_secret_run_role(
                'production', self.config_path,
                secret_run_command='secret-run', runner=failing_runner,
            ),
            1,
        )


if __name__ == '__main__':
    unittest.main()
