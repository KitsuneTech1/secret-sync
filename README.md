# secret-sync

`secret-sync` copies an allowlisted set of secret values in one direction. It
can read local JSON or dotenv files, or run under `secret-run` to receive
selected Proton Pass items. It writes either a dotenv file or one AWS Secrets
Manager secret. `--dry-run` shows the names and destination without writing.

There are no bidirectional writes.

## Requirements

- Python 3.8 or newer
- `secret-run` on `PATH` for Proton Pass input
- AWS CLI on `PATH` for an AWS Secrets Manager destination

The local-file mode only uses the Python standard library. No package
installation is required.

## Configuration

Create a JSON file with the names to copy and the destination:

```json
{
  "secrets": ["API_KEY", "DB_PASSWORD"],
  "destination": ".env.local"
}
```

The names must be unique, non-empty environment variable names using letters,
digits, and underscores, with a letter or underscore first. A dotenv destination
is replaced with the selected entries on each non-dry run. Missing names are
reported, and the command fails if none of the approved names are present.

For AWS Secrets Manager, use an object destination:

```json
{
  "secrets": ["API_KEY", "DB_PASSWORD"],
  "destination": {
    "type": "aws-secrets-manager",
    "name": "my-app/config",
    "region": "us-east-1"
  }
}
```

`region` and `profile` are optional. The AWS secret value is a JSON object
containing only the selected names. An existing secret gets a new version. A
missing secret is created.

## Usage

Run from a local JSON source:

```bash
python sync.py config.json --source secrets.json
```

Run from a dotenv source:

```bash
python sync.py config.json --source .env.production
```

Run with Proton Pass through `secret-run`:

```bash
python sync.py config.json --role production
```

The `production` role must map the configured names to Proton Pass items. For
example, `API_KEY = My API key` in the role file provides the `API_KEY` value.
`secret-run` starts a child sync process with the values in its environment.
`secret-sync` does not print those values.

Preview any source without writing:

```bash
python sync.py config.json --source secrets.json --dry-run
python sync.py config.json --role production --dry-run
```

Generate a placeholder dotenv file without reading secrets:

```bash
python sync.py config.json --stub
```

`--stub` requires a dotenv path destination. It writes `CHANGE_ME` for every
approved name.

## Source formats

JSON sources contain an object:

```json
{
  "API_KEY": "actual-key-value",
  "DB_PASSWORD": "actual-password"
}
```

Dotenv sources support comments, `export NAME=value`, quoted values, and a
single `=` separator:

```dotenv
API_KEY="actual-key-value"
DB_PASSWORD=actual-password
```

Only names listed in the configuration are copied. Extra source values are
ignored.

## AWS behavior

AWS mode calls the AWS CLI `secretsmanager` commands. It captures CLI output so
secret values are not printed by this tool. If the AWS CLI is missing, the
command exits with a message that explains how to use a dotenv destination
instead.

AWS credentials and permissions are supplied by the normal AWS CLI
configuration. Tests do not contact AWS.

## Testing

```bash
python -m unittest -v
```

The test suite uses local fixtures and mocked subprocess calls. It does not
contact Proton Pass, AWS, or any other network service.

## License

MIT License

Copyright (c) 2026 KitsuneTech1
