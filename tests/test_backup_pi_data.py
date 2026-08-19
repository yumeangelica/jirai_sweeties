import os
import shutil
import sqlite3
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = PROJECT_ROOT / "scripts" / "backup_pi_data.sh"


class BackupPiDataScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.root = Path(self.temp_directory.name)

        self.repo = self.root / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        self.script = self.repo / "scripts" / "backup_pi_data.sh"
        shutil.copy2(BACKUP_SCRIPT, self.script)
        self.script.chmod(0o755)

        self.local_data = self.repo / "data"
        self.local_data.mkdir()
        self.create_database(self.local_data / "discord_db.sqlite", "local-discord")
        self.create_database(self.local_data / "store_db.sqlite", "local-store")

        self.remote_data = self.root / "docker-volume-data"
        self.remote_data.mkdir(parents=True)
        self.create_database(
            self.remote_data / "discord_db.sqlite", "remote-discord"
        )
        self.create_database(self.remote_data / "store_db.sqlite", "remote-store")

        self.remote_state = self.root / "remote-container-state"
        self.remote_state.write_text("true", encoding="utf-8")
        self.backup_root = self.root / "backups"
        self.mock_bin = self.root / "mock-bin"
        self.mock_bin.mkdir()
        self.write_mock_commands()

    @staticmethod
    def create_database(path: Path, marker: str) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
            connection.execute("INSERT INTO marker (value) VALUES (?)", (marker,))
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def read_marker(path: Path) -> str:
        connection = sqlite3.connect(path)
        try:
            return connection.execute("SELECT value FROM marker").fetchone()[0]
        finally:
            connection.close()

    def write_mock_commands(self) -> None:
        ssh_mock = self.mock_bin / "ssh"
        ssh_mock.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                remote_command="${!#}"
                case "$remote_command" in
                  true)
                    exit 0
                    ;;
                  *"command -v docker"*)
                    printf 'discord-bot:latest\n'
                    printf 'volume:/var/lib/docker/volumes/discord-bot-data/_data\n'
                    ;;
                  *"--entrypoint sh"*)
                    test -f "$FAKE_REMOTE_DATA/discord_db.sqlite" || {
                      printf 'database missing: /app/data/discord_db.sqlite\n'
                      exit 13
                    }
                    test -f "$FAKE_REMOTE_DATA/store_db.sqlite" || {
                      printf 'database missing: /app/data/store_db.sqlite\n'
                      exit 14
                    }
                    ;;
                  *"{{.State.Running}}"*)
                    cat "$FAKE_REMOTE_STATE"
                    ;;
                  *"docker stop"*)
                    printf 'false' > "$FAKE_REMOTE_STATE"
                    ;;
                  *"--entrypoint tar"*)
                    if [ "${FAKE_TRANSFER_MODE:-success}" = "partial" ]; then
                      printf 'truncated transfer'
                      exit 23
                    fi
                    tar -C "$FAKE_REMOTE_DATA" -cf - .
                    ;;
                  *"docker start"*)
                    printf 'true' > "$FAKE_REMOTE_STATE"
                    ;;
                  *)
                    printf 'unexpected mock SSH command: %s\n' "$remote_command" >&2
                    exit 64
                    ;;
                esac
                """
            ),
            encoding="utf-8",
        )
        ssh_mock.chmod(0o755)

        docker_mock = self.mock_bin / "docker"
        docker_mock.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                if [ "${1:-}" = "inspect" ]; then
                  printf 'false'
                fi
                """
            ),
            encoding="utf-8",
        )
        docker_mock.chmod(0o755)

    def run_backup(self, transfer_mode: str = "success") -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.mock_bin}:{environment['PATH']}",
                "PI_HOST": "pi.test",
                "PI_USER": "pi",
                "BACKUP_ROOT": str(self.backup_root),
                "FAKE_REMOTE_DATA": str(self.remote_data),
                "FAKE_REMOTE_STATE": str(self.remote_state),
                "FAKE_TRANSFER_MODE": transfer_mode,
            }
        )
        return subprocess.run(
            [str(self.script), "--update-local"],
            cwd=self.repo,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_verified_snapshot_updates_local_data_and_preserves_old_data(self) -> None:
        result = self.run_backup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote_state.read_text(encoding="utf-8"), "true")
        self.assertIn("volume:/var/lib/docker/volumes/discord-bot-data/_data", result.stdout)
        snapshots = list(self.backup_root.glob("pi-data-*"))
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]

        self.assertEqual(
            self.read_marker(snapshot / "remote-data" / "discord_db.sqlite"),
            "remote-discord",
        )
        self.assertEqual(
            self.read_marker(snapshot / "local-data-before-update" / "store_db.sqlite"),
            "local-store",
        )
        self.assertEqual(
            self.read_marker(self.local_data / "discord_db.sqlite"),
            "remote-discord",
        )
        self.assertIn("remote-data/store_db.sqlite", (snapshot / "SHA256SUMS").read_text())

    def test_corrupt_remote_database_keeps_local_data_and_restarts_remote(self) -> None:
        (self.remote_data / "discord_db.sqlite").write_text(
            "not a SQLite database", encoding="utf-8"
        )

        result = self.run_backup()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.remote_state.read_text(encoding="utf-8"), "true")
        self.assertEqual(list(self.backup_root.glob("pi-data-*")), [])
        self.assertEqual(
            self.read_marker(self.local_data / "discord_db.sqlite"), "local-discord"
        )
        self.assertEqual(list(self.backup_root.glob(".pi-data-*.partial.*")), [])

    def test_partial_transfer_keeps_local_data_and_restarts_remote(self) -> None:
        result = self.run_backup(transfer_mode="partial")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.remote_state.read_text(encoding="utf-8"), "true")
        self.assertEqual(list(self.backup_root.glob("pi-data-*")), [])
        self.assertEqual(
            self.read_marker(self.local_data / "store_db.sqlite"), "local-store"
        )
        self.assertEqual(list(self.backup_root.glob(".pi-data-*.partial.*")), [])

    def test_missing_volume_database_reports_exact_path_before_stopping(self) -> None:
        (self.remote_data / "store_db.sqlite").unlink()

        result = self.run_backup()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "database missing: /app/data/store_db.sqlite",
            result.stderr,
        )
        self.assertEqual(self.remote_state.read_text(encoding="utf-8"), "true")
        self.assertEqual(list(self.backup_root.glob("pi-data-*")), [])
        self.assertEqual(
            self.read_marker(self.local_data / "store_db.sqlite"), "local-store"
        )


if __name__ == "__main__":
    unittest.main()
