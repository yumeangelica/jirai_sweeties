# Jirai Sweeties repository guidance

## Runtime and data model

- This is a Python 3.14 Discord bot managed with `uv` and deployed as the `discord-bot` Docker Compose service on a 64-bit (`aarch64`) Raspberry Pi.
- `bot/discord_database.py` owns `data/discord_db.sqlite` (Discord member records). `store_data_extractor/src/store_database.py` owns `data/store_db.sqlite` (stores, products, prices, and notification state).
- Both databases enable SQLite WAL mode. For a running Pi, the container's actual `/app/data` mount is the source of truth—not a host directory that merely has the same name.
- The current Compose contract is `./data:/app/data`. An old installation may still use a Docker named volume. Never change between those layouts implicitly.
- Production files under `bot/config/` and `store_data_extractor/config/` are intentionally ignored by Git and baked into the image. `.env` is supplied to Compose at runtime.

## Safe Pi operations

- Read `docs/raspberry-pi-runbook.md` before backup, shutdown, OS reinstall, restore, mount migration, or deploy work.
- Use `scripts/backup_pi_data.sh`; never copy only a live `.sqlite` file. It stops the writer, copies the complete actual mount, checks both databases, writes checksums, and restores the prior container state.
- Use `scripts/restore_pi_data.sh` only with a verified snapshot and a stopped container whose `/app/data` is empty. It intentionally refuses to overwrite data.
- Use `scripts/deploy_pi.sh --keep-db`; keeping both Pi databases is the default. `--replace-db` and `--fresh-db` require an explicit user request.
- The deploy script must refuse any implicit named-volume-to-bind-mount transition. Resolve it with the documented backup/reinstall/restore flow.
- Keep scripts non-interactive and fail-fast. Connection settings come from `PI_HOST`, `PI_USER`, `PI_DIR`, and optionally `PI_CONTAINER`; never hard-code a personal IP or username in tracked files.
- Never power off, reformat, wipe, restore over, or delete Pi data without the user's explicit authorization. A completed backup does not authorize shutdown.

## Development commands

```bash
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python scripts/smoke_compile.py
bash -n scripts/backup_pi_data.sh scripts/restore_pi_data.sh scripts/deploy_pi.sh
```

- Prefer the smallest targeted unittest module while editing; run the full offline suite before handing off a wider behavioral change.
- Do not start the real Discord bot as a test. Live scraper checks are opt-in and are documented in `README.md`.
- Keep Pi data-transfer regression tests self-contained with mocked `ssh`/`docker`; they must never require a live Pi.

## Repository safety

- Never commit `data/`, `backups/`, `.env`, production config, SSH keys, device addresses, or image archives.
- Preserve unrelated work in a dirty tree. Do not silently replace runtime databases or user config.
- Ask before every commit. Ask separately before every push or PR.
