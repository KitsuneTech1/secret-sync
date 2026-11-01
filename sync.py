#!/usr/bin/env python3
"""Sync selected secrets one way to a dotenv file or AWS Secrets Manager."""

import json
import os
import re
import shutil
import subprocess
import sys
from argparse import ArgumentParser, SUPPRESS
from pathlib import Path


class SyncError(Exception):
    """A user-facing sync failure that should not expose secret values."""


ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def fail(message):
    """Print a configuration error and preserve the original CLI behavior."""
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_config(config_path):
    """Load a JSON sync configuration file."""
    try:
        with open(config_path, "r", encoding="utf-8-sig") as config_file:
            return json.load(config_file)
    except FileNotFoundError:
        fail(f"Config file not found: {config_path}")
    except json.JSONDecodeError as error:
        fail(f"Invalid JSON in {config_path}: {error}")
    except OSError as error:
        fail(f"Could not read config {config_path}: {error}")


def validate_config(config):
    """Validate the supported configuration shapes."""
    if not isinstance(config, dict):
        fail("config must be a JSON object")

    for key in ("secrets", "destination"):
        if key not in config:
            fail(f"Missing required key in config: {key}")

    names = config["secrets"]
    if not isinstance(names, list):
        fail("'secrets' must be a list")
    if any(not isinstance(name, str) or not name.strip() for name in names):
        fail("'secrets' must contain non-empty strings")
    if any(not ENV_NAME_PATTERN.fullmatch(name) for name in names):
        fail("'secrets' must contain valid environment variable names")
    if len(set(names)) != len(names):
        fail("'secrets' must not contain duplicates")

    destination = config["destination"]
    if isinstance(destination, str):
        if not destination.strip():
            fail("'destination' must not be empty")
        return
    if not isinstance(destination, dict):
        fail("'destination' must be a path or an AWS destination object")
    destination_type = destination.get("type")
    if destination_type not in ("aws", "aws-secrets-manager"):
        fail("AWS destination type must be 'aws-secrets-manager'")
    if not isinstance(destination.get("name"), str) or not destination["name"].strip():
        fail("AWS destination requires a non-empty 'name'")
    for key in ("region", "profile"):
        if key in destination and (not isinstance(destination[key], str) or not destination[key].strip()):
            fail(f"AWS destination '{key}' must be a non-empty string")


def destination_details(destination):
    """Return the destination kind and its normalized settings."""
    if isinstance(destination, str):
        return "env", {"path": destination}
    details = dict(destination)
    details["type"] = "aws"
    return "aws", details


def format_env_entry(name, value):
    """Format a secret as one quoted dotenv entry."""
    value_str = str(value)
    value_str = (value_str.replace("\\", "\\\\")
                 .replace("\r", "\\r")
                 .replace("\n", "\\n")
                 .replace('"', '\\"'))
    return f'{name}="{value_str}"'


def parse_env_value(raw_value):
    """Parse the small dotenv value subset used by secret-sync."""
    value = raw_value.strip()
    if value.startswith('"'):
        try:
            parsed, end = json.JSONDecoder().raw_decode(value)
        except json.JSONDecodeError as error:
            raise SyncError(f"invalid double-quoted dotenv value: {error}") from error
        trailing = value[end:].strip()
        if trailing and not trailing.startswith("#"):
            raise SyncError("unexpected text after double-quoted dotenv value")
        return parsed
    if value.startswith("'"):
        end = value.find("'", 1)
        if end < 0:
            raise SyncError("unterminated single-quoted dotenv value")
        trailing = value[end + 1:].strip()
        if trailing and not trailing.startswith("#"):
            raise SyncError("unexpected text after single-quoted dotenv value")
        return value[1:end]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def load_secrets_from_file(secrets_path):
    """Load secrets from JSON or a dotenv file."""
    path = Path(secrets_path)
    try:
        if path.suffix.lower() == ".json":
            with open(path, "r", encoding="utf-8-sig") as source_file:
                secrets = json.load(source_file)
            if not isinstance(secrets, dict):
                raise SyncError("JSON source must contain an object")
            return secrets

        lower_name = path.name.lower()
        if path.suffix.lower() == ".env" or lower_name == ".env" or lower_name.startswith(".env."):
            secrets = {}
            with open(path, "r", encoding="utf-8") as source_file:
                for line_number, raw_line in enumerate(source_file, 1):
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:].lstrip()
                    if "=" not in line:
                        raise SyncError(f"invalid dotenv line {line_number} in {path}")
                    key, raw_value = line.split("=", 1)
                    key = key.strip()
                    if not key:
                        raise SyncError(f"empty dotenv name on line {line_number} in {path}")
                    secrets[key] = parse_env_value(raw_value)
            return secrets
    except FileNotFoundError as error:
        raise SyncError(f"source file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise SyncError(f"invalid JSON in {path}: {error}") from error
    except OSError as error:
        raise SyncError(f"could not read source {path}: {error}") from error

    raise SyncError(f"unsupported source format: {path.suffix or path.name}")


def load_secrets_from_environment(approved_names, environ=None):
    """Read the approved names from variables injected by secret-run."""
    environment = os.environ if environ is None else environ
    missing = [name for name in approved_names if name not in environment]
    if missing:
        raise SyncError("secret-run did not provide: " + ", ".join(missing))
    return {name: environment[name] for name in approved_names}


def approved_values(secrets, approved_names):
    """Return selected values in configured order and report missing names."""
    selected = {}
    missing = []
    for name in approved_names:
        if name in secrets:
            selected[name] = secrets[name]
        else:
            missing.append(name)
    for name in missing:
        print(f"Warning: Secret not found in source: {name}", file=sys.stderr)
    if not selected:
        raise SyncError("none of the approved secrets were found in the source")
    return selected


def write_text(destination, content):
    """Write a destination file, creating its parent directory when needed."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def generate_env_file(secrets, approved_names, destination, dry_run=False):
    """Generate a dotenv file with only approved secrets."""
    selected = approved_values(secrets, approved_names)
    content = "\n".join(format_env_entry(name, value) for name, value in selected.items()) + "\n"

    if dry_run:
        print(f"DRY RUN: Would write {len(selected)} secrets to {destination}")
        print(f"Secrets: {', '.join(selected)}")
        return True

    write_text(destination, content)
    print(f"Synced {len(selected)} secrets to {destination}")
    return True


def generate_stub_file(approved_names, destination, dry_run=False):
    """Generate a dotenv template without actual values."""
    content = "# Stub file - fill in actual values\n"
    content += "\n".join(f'{name}="CHANGE_ME"' for name in approved_names) + "\n"

    if dry_run:
        print(f"DRY RUN: Would write {len(approved_names)} stub entries to {destination}")
        print(f"Secrets: {', '.join(approved_names)}")
        return True

    write_text(destination, content)
    print(f"Generated stub file with {len(approved_names)} secrets to {destination}")
    return True


def run_aws(command, runner):
    """Run AWS CLI quietly and convert missing-tool errors to a clear message."""
    try:
        return runner(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise SyncError(
            "AWS CLI was not found. Install AWS CLI or use a dotenv destination."
        ) from error
    except OSError as error:
        raise SyncError(f"could not start AWS CLI: {error}") from error


def sync_to_aws(secrets, approved_names, secret_name, dry_run=False, region=None,
                profile=None, runner=None, aws_command="aws"):
    """Create or update one AWS Secrets Manager secret with selected values."""
    selected = approved_values(secrets, approved_names)
    payload = json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
    runner = runner or subprocess.run

    if dry_run:
        print(f"DRY RUN: Would write {len(selected)} secrets to AWS Secrets Manager {secret_name}")
        print(f"Secrets: {', '.join(selected)}")
        return True

    def command(*args):
        built = [aws_command, "secretsmanager", *args]
        if region:
            built.extend(["--region", region])
        if profile:
            built.extend(["--profile", profile])
        return built

    describe = run_aws(command("describe-secret", "--secret-id", secret_name), runner)
    if describe.returncode == 0:
        action = command(
            "put-secret-value", "--secret-id", secret_name,
            "--secret-string", payload,
        )
    elif "resourcenotfoundexception" in (describe.stderr or "").lower():
        action = command(
            "create-secret", "--name", secret_name,
            "--secret-string", payload,
        )
    else:
        raise SyncError(f"AWS Secrets Manager lookup failed for {secret_name!r}")

    result = run_aws(action, runner)
    if result.returncode != 0:
        raise SyncError(f"AWS Secrets Manager write failed for {secret_name!r}")
    print(f"Synced {len(selected)} secrets to AWS Secrets Manager {secret_name}")
    return True


def run_secret_run_role(role, config_path, dry_run=False, secret_run_command=None,
                        runner=None):
    """Run this program under secret-run so values stay in the child process."""
    secret_run_command = secret_run_command or shutil.which("secret-run")
    runner = runner or subprocess.run
    if not secret_run_command:
        print(
            "Error: secret-run was not found. Install secret-run and add it to PATH.",
            file=sys.stderr,
        )
        return 1

    command = [
        secret_run_command,
        role,
        "--reason",
        "secret-sync",
        "--",
        sys.executable,
        str(Path(__file__).resolve()),
        str(Path(config_path).resolve()),
        "--source-env",
    ]
    if dry_run:
        command.append("--dry-run")
    result = runner(command, check=False)
    if result.returncode != 0:
        print(f"Error: secret-run failed with exit code {result.returncode}", file=sys.stderr)
    return result.returncode


def build_parser():
    """Build the command-line parser."""
    parser = ArgumentParser(description="Sync approved secrets one way to a file or AWS.")
    parser.add_argument("config", help="Path to sync configuration (JSON)")
    parser.add_argument("--source", help="Path to a JSON or dotenv source file")
    parser.add_argument("--role", help="secret-run role containing the approved Proton Pass items")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be written")
    parser.add_argument("--stub", action="store_true", help="Write a placeholder dotenv file")
    parser.add_argument("--source-env", action="store_true", help=SUPPRESS)
    return parser


def main(argv=None):
    """Run the CLI and return its process exit code."""
    args = build_parser().parse_args(argv)

    if args.source and args.role:
        print("Error: choose --source or --role, not both", file=sys.stderr)
        return 1
    if args.source_env and (args.source or args.role or args.stub):
        print("Error: --source-env cannot be combined with --source, --role, or --stub", file=sys.stderr)
        return 1
    if args.role and args.stub:
        print("Error: --role cannot be combined with --stub", file=sys.stderr)
        return 1

    config = load_config(args.config)
    validate_config(config)
    approved_names = config["secrets"]

    if args.role:
        return run_secret_run_role(args.role, args.config, args.dry_run)

    try:
        if args.stub:
            kind, destination = destination_details(config["destination"])
            if kind != "env":
                raise SyncError("--stub requires a dotenv path destination")
            generate_stub_file(approved_names, destination["path"], args.dry_run)
            return 0

        if args.source_env:
            secrets = load_secrets_from_environment(approved_names)
        else:
            if not args.source:
                print("Error: --source or --role is required", file=sys.stderr)
                return 1
            secrets = load_secrets_from_file(args.source)

        kind, destination = destination_details(config["destination"])
        if kind == "env":
            generate_env_file(secrets, approved_names, destination["path"], args.dry_run)
        else:
            sync_to_aws(
                secrets,
                approved_names,
                destination["name"],
                args.dry_run,
                region=destination.get("region"),
                profile=destination.get("profile"),
            )
        return 0
    except SyncError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
