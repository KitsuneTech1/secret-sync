#!/usr/bin/env python3
"""Sync approved secrets one-way from a source to a destination (env file or stub)."""

import json
import sys
from pathlib import Path
from argparse import ArgumentParser
from datetime import datetime


def load_config(config_path):
    """Load sync configuration file."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {config_path}: {e}", file=sys.stderr)
        sys.exit(1)


def validate_config(config):
    """Validate configuration structure."""
    required = ['secrets', 'destination']
    for key in required:
        if key not in config:
            print(f"Error: Missing required key in config: {key}", file=sys.stderr)
            sys.exit(1)

    if not isinstance(config['secrets'], list):
        print("Error: 'secrets' must be a list", file=sys.stderr)
        sys.exit(1)


def format_env_entry(name, value):
    """Format a secret as an environment variable entry."""
    # Escape quotes and newlines
    value_str = str(value).replace('\\', '\\\\').replace('"', '\\"')
    return f'{name}="{value_str}"'


def load_secrets_from_file(secrets_path):
    """Load actual secrets from a source file."""
    secrets_path = Path(secrets_path)
    if secrets_path.suffix == '.json':
        with open(secrets_path, 'r') as f:
            return json.load(f)
    elif secrets_path.suffix == '.env':
        # Parse simple key=value format
        secrets = {}
        with open(secrets_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    secrets[key] = val.strip('"\'')
        return secrets
    else:
        print(f"Error: Unsupported source format: {secrets_path.suffix}", file=sys.stderr)
        sys.exit(1)


def generate_env_file(secrets, approved_names, destination, dry_run=False):
    """Generate or update .env file with approved secrets."""
    env_lines = []
    found = set()

    for name in approved_names:
        if name in secrets:
            env_lines.append(format_env_entry(name, secrets[name]))
            found.add(name)
        else:
            print(f"Warning: Secret not found in source: {name}", file=sys.stderr)

    content = '\n'.join(env_lines) + '\n'

    if dry_run:
        print(f"DRY RUN: Would write {len(found)} secrets to {destination}")
        print(f"Secrets: {', '.join(found)}")
        return True

    dest_path = Path(destination)
    dest_path.write_text(content)
    print(f"Synced {len(found)} secrets to {destination}")
    return True


def generate_stub_file(approved_names, destination, dry_run=False):
    """Generate a stub .env file with placeholders (no actual values)."""
    env_lines = [f'{name}="CHANGE_ME"' for name in approved_names]
    content = '# Stub file - fill in actual values\n' + '\n'.join(env_lines) + '\n'

    if dry_run:
        print(f"DRY RUN: Would write {len(approved_names)} stub entries to {destination}")
        print(f"Secrets: {', '.join(approved_names)}")
        return True

    dest_path = Path(destination)
    dest_path.write_text(content)
    print(f"Generated stub file with {len(approved_names)} secrets to {destination}")
    return True


def main():
    parser = ArgumentParser(description='Sync approved secrets one-way to a destination.')
    parser.add_argument('config', help='Path to sync configuration (JSON)')
    parser.add_argument('--source', help='Path to source secrets file (JSON or .env)')
    parser.add_argument('--dry-run', action='store_true', default=False,
                        help='Show what would be synced without writing')
    parser.add_argument('--stub', action='store_true', default=False,
                        help='Generate stub file with placeholders instead of actual values')

    args = parser.parse_args()

    config = load_config(args.config)
    validate_config(config)

    approved_names = config.get('secrets', [])
    destination = config.get('destination')

    if not approved_names:
        print("Error: No secrets specified in configuration", file=sys.stderr)
        sys.exit(1)

    if args.stub:
        generate_stub_file(approved_names, destination, args.dry_run)
    else:
        if not args.source:
            print("Error: --source is required when not using --stub", file=sys.stderr)
            sys.exit(1)

        secrets = load_secrets_from_file(args.source)
        generate_env_file(secrets, approved_names, destination, args.dry_run)


if __name__ == '__main__':
    main()
