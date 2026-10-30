# ledger-lab

Getting started. The project description, stack, and agent instructions are in [AGENTS.md](AGENTS.md).

## Layout

- [AGENTS.md](AGENTS.md) is the project description.
- [.cursor/rules/engineering.mdc](.cursor/rules/engineering.mdc) and [.cursor/rules/ledger-principles.mdc](.cursor/rules/ledger-principles.mdc) are the Cursor rules.
- [docs/architecture/README.md](docs/architecture/README.md) is the architecture entry point.
- `src/ledger_lab/` is the node. It serves `GET /health` and `GET /ready`.
- `tests/` is the pytest suite.
- `Dockerfile` and `docker-compose.yml` run the node and Postgres.
- `.github/workflows/ci.yml` is CI.
- `.pre-commit-config.yaml` holds the ruff, ruff format, and mypy commands.
- `pyproject.toml`, `uv.lock`, and `.python-version` pin the toolchain.

## Prerequisites

- Python 3.15 or newer (`requires-python` in `pyproject.toml`). `.python-version` pins 3.15.2. `uv sync` installs that interpreter.
- uv 0.13.6 (`required-version` in `pyproject.toml`).
- Docker with Compose (`docker compose`).

Running the stack needs Docker. Local development and the checks need uv.

## Running

This starts Postgres (`postgres:16.15-alpine3.24`) and the node. Both services have healthchecks. The command returns when both are healthy.

```bash
docker compose up --build --wait
```

The node listens on port 8080.

```bash
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
```

`/health` is liveness and returns `{"status": "ok"}`. `/ready` runs `SELECT 1` and returns `{"status": "ready"}`.

Stop the stack:

```bash
docker compose down
```

That removes the containers and the network. The Postgres volume `postgres_data` stays. `docker compose down -v` removes that volume.

Unset variables use the local placeholders in `docker-compose.yml`: user `ledger`, password `ledger`, database `ledger`. The same values are listed in `.env.example`. They are for this machine.

## Local development

Postgres stays in Compose. The node runs on the host and uses the port Compose publishes.

```bash
uv sync
docker compose up --detach --wait postgres
```

`uv sync` creates `.venv` and installs the project and the dev tools (ruff, mypy, pytest, and pre-commit). `uv run` uses that interpreter (Python 3.15.2). The Postgres command returns when its healthcheck is healthy. Compose publishes Postgres on host port 5432.

```bash
export DATABASE_URL=postgresql://ledger:ledger@127.0.0.1:5432/ledger
uv run python -m ledger_lab
```

`DATABASE_URL` is required. The user, password, and database in that URL are the local placeholders (`ledger`, `ledger`, and `ledger`). With `PORT`, `LOG_LEVEL`, and `DB_CONNECT_TIMEOUT_SECONDS` unset, the process listens on port 8080, logs at `INFO`, and uses a database timeout of 3 seconds.

`uv run ledger-lab` calls the same `main`. The image command is `ledger-lab`.

Ctrl+C sends SIGINT. The process closes the listening socket and exits 0.

Stop Postgres with `docker compose down`. Add `-v` to delete the data volume.

## Checks before a pull request

```bash
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest
```

`pre-commit install` writes `.git/hooks/pre-commit`. That hook, and `pre-commit run --all-files`, run ruff check, ruff format --check, and mypy. Tool settings live in `pyproject.toml`. pytest does not need a running Postgres.

CI in `.github/workflows/ci.yml` runs on pull requests and on pushes to `main`.

- `lint, typecheck, and test` runs `uv sync --frozen`, `uv run pre-commit run --all-files`, and `uv run pytest`.
- `docker compose up --wait` runs `docker compose up --build --wait`, then `docker compose down -v`.

## Troubleshooting

Compose publishes Postgres on port 5432 and the node on port 8080. A process already listening on one of those ports stops that service from starting.

From the host, `DATABASE_URL` uses `127.0.0.1` and port 5432. The hostname `postgres` is the Compose service name, used by the node container. A host process with that hostname gets `503` and `{"status": "not_ready", "reason": "unreachable"}` from `/ready`. `.env.example` contains the container URL. The host command above is the one that reaches Postgres.
