#!/usr/bin/env python3
"""Tests for secret-sync."""

import unittest
import tempfile
import json
from pathlib import Path
import sync


class TestSecretSync(unittest.TestCase):
    """Test secret-sync functionality."""

    def setUp(self):
        """Create temporary files for testing."""
        self.temp_dir = Path(tempfile.mkdtemp())

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

    def test_load_config(self):
        """Test loading configuration."""
        config = sync.load_config(self.config_path)
        self.assertIn('secrets', config)
        self.assertIn('destination', config)

    def test_validate_config_valid(self):
        """Test validation of valid config."""
        config = {"secrets": ["KEY1"], "destination": "/tmp/test"}
        # Should not raise
        sync.validate_config(config)

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

    def test_format_env_entry(self):
        """Test formatting environment variable entry."""
        entry = sync.format_env_entry('TEST_KEY', 'test_value')
        self.assertEqual(entry, 'TEST_KEY="test_value"')

    def test_format_env_entry_with_quotes(self):
        """Test formatting with quotes in value."""
        entry = sync.format_env_entry('KEY', 'value"with"quotes')
        self.assertIn('\\"', entry)

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


if __name__ == '__main__':
    unittest.main()
