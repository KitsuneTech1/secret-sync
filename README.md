# secret-sync

Move an approved set of secrets one way between approved places with a dry run option.

## What it does

Syncs a defined list of secrets from a source file (JSON or .env) to a destination, ensuring only approved secrets are transferred. Supports:

- JSON or .env format source files
- Whitelist-based secret filtering
- Dry run mode to preview sync without writing
- Stub mode to generate placeholder files

No bidirectional writes. One-way only.

## Installation

```bash
pip install -e .
```

Or run directly:

```bash
python sync.py <config.json> [options]
```

## Usage

### Configuration file

Create a JSON configuration file that specifies which secrets to sync:

```json
{
  "secrets": ["API_KEY", "DB_PASSWORD", "SLACK_TOKEN"],
  "destination": ".env"
}
```

### Sync from JSON source

```bash
python sync.py config.json --source secrets.json
```

This reads all secrets from secrets.json and syncs only the approved ones to .env.

### Sync from .env source

```bash
python sync.py config.json --source .env.production
```

Parses the source .env file and syncs approved entries.

### Dry run (preview without writing)

```bash
python sync.py config.json --source secrets.json --dry-run
```

Prints what would be synced without actually writing the file.

### Generate stub file (no values)

```bash
python sync.py config.json --stub
```

Creates a .env file with placeholder values (all set to "CHANGE_ME") for the approved secrets. Useful for sharing configuration templates.

### Combine options

```bash
python sync.py config.json --source secrets.json --dry-run --stub
```

## Config file format

```json
{
  "secrets": [
    "API_KEY",
    "DATABASE_URL",
    "SIGNING_KEY"
  ],
  "destination": ".env.local"
}
```

- secrets: list of secret names to approve for syncing
- destination: output file path (any format, typically .env)

## Source file formats

JSON:
```json
{
  "API_KEY": "actual-key-value",
  "DB_PASSWORD": "actual-password"
}
```

.env:
```
API_KEY=actual-key-value
DB_PASSWORD=actual-password
```

## Security

- Only approved secrets (listed in config) are synced
- Actual secret values are never logged or printed unless explicitly requested
- Dry run mode lets you review exactly what will be written before committing
- Stub mode (--stub) removes all actual values and replaces with placeholders

## Testing

```bash
python -m unittest test_sync
```

## License

MIT License

Copyright (c) 2026 KitsuneTech1
