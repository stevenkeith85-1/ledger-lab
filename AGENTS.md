# Ledger Lab

Ledger Lab is a Python UTXO blockchain. It uses Ed25519 signatures and SHA-256 hashing, stores state in Postgres, and runs in Docker as a GCP-ready service. A React or Angular front end comes later. The repository is built with Cursor agents for a video series and a NatWest Principal Engineer (Digital Assets) interview, so the code stays small, typed, and tested.

This file is the only copy of that description.

## Stack

Pinned in the file named here.

- Python: `.python-version`
- PostgreSQL: image in `docker-compose.yml`
- Packaging and lockfile: `pyproject.toml`, `uv.lock`
- uv: `[tool.uv] required-version` in `pyproject.toml`
- Lint, format, types, and tests: settings in `pyproject.toml`
- Lint, format, and typecheck commands: `.pre-commit-config.yaml`
- Containers: `Dockerfile`, `docker-compose.yml`
- Runtime: configuration from the environment, listen port from `PORT`, logs on stdout
- Front end: React or Angular, not in this repository yet

## Documents

- Architecture, owned by Alf: [docs/architecture/README.md](docs/architecture/README.md)
- Engineering rules: [.cursor/rules/engineering.mdc](.cursor/rules/engineering.mdc)
- Ledger principles: [.cursor/rules/ledger-principles.mdc](.cursor/rules/ledger-principles.mdc)

## Layout

`src/ledger_lab/` is the node process. It serves `/health` and `/ready`. `/ready` checks Postgres. There is no ledger logic in this scaffold.

## Setup

Install uv at the version required in `pyproject.toml`. Then:

```bash
uv sync
uv run pre-commit install
```

`docker compose up --build --wait` uses the local placeholders in `docker-compose.yml`. Copy `.env.example` to `.env` only to override them.

## Checks

```bash
uv run pre-commit run --all-files
uv run pytest
docker compose up --build --wait
docker compose down -v
```

GitHub Actions runs those checks on pull requests and on pushes to `main`. The workflow is `.github/workflows/ci.yml`.
