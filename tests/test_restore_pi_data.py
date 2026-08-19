import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESTORE_SCRIPT = PROJECT_ROOT / "scripts" / "restore_pi_data.sh"


class RestorePiDataScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.root = Path(self.temp_directory.name)

        self.repo = self.root / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        self.script = self.repo / "scripts" / "restore_pi_data.sh"
        shutil.copy2(RESTORE_SCRIPT, self.script)
        self.script.chmod(0o755)

        self.snapshot = self.root / "pi-data-20260812-214712"
        self.snapshot_data = self.snapshot / "remote-data"
        self.snapshot_data.mkdir(parents=True)
        self.create_database(
            self.snapshot_data / "discord_db.sqlite", "snapshot-discord"
        )
        self.create_database(
            self.snapshot_data / "store_db.sqlite", "snapshot-store"
        )
        self.write_manifest()

        self.remote_data = self.root / "new-pi-volume"
        self.remote_data.mkdir()
        self.remote_state = self.root / "remote-container-state"
        self.remote_state.write_text("false", encoding="utf-8")

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

    def write_manifest(self) -> None:
        lines = []
        for path in sorted(item for item in self.snapshot_data.rglob("*") if item.is_file()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(self.snapshot)}\n")
        (self.snapshot / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")

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
                  *"{{.State.Running}}"*)
                    cat "$FAKE_REMOTE_STATE"
                    ;;
                  *"sum(1 for"*)
                    find "$FAKE_REMOTE_DATA" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d ' '
                    ;;
                  *"--entrypoint tar"*)
                    if [ "${FAKE_TRANSFER_MODE:-success}" = "partial" ]; then
                      touch "$FAKE_REMOTE_DATA/partial-transfer"
                      cat >/dev/null
                      exit 23
                    fi
                    tar -C "$FAKE_REMOTE_DATA" -xf -
                    ;;
                  *"shutil"*"path.unlink"*)
                    python3 -c '
import shutil
from pathlib import Path
root = Path("'"$FAKE_REMOTE_DATA"'")
for path in root.iterdir():
    shutil.rmtree(path) if path.is_dir() else path.unlink()
'
                    ;;
                  *"--entrypoint python"*)
                    cat >/dev/null
                    python3 - "$FAKE_REMOTE_DATA" <<'PY'
import sqlite3
import sys
from pathlib import Path

root = Path(sys.argv[1])
for name in ("discord_db.sqlite", "store_db.sqlite"):
    connection = sqlite3.connect(root / name)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchall()
    finally:
        connection.close()
    if result != [("ok",)]:
        raise SystemExit(1)
PY
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

    def run_restore(
        self, *, start: bool = False, transfer_mode: str = "success"
    ) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.mock_bin}:{environment['PATH']}",
                "PI_HOST": "pi.test",
                "PI_USER": "pi",
                "FAKE_REMOTE_DATA": str(self.remote_data),
                "FAKE_REMOTE_STATE": str(self.remote_state),
                "FAKE_TRANSFER_MODE": transfer_mode,
            }
        )
        command = [str(self.script), str(self.snapshot)]
        if start:
            command.append("--start")
        return subprocess.run(
            command,
            cwd=self.repo,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_verified_snapshot_restores_to_empty_mount_and_starts_container(self) -> None:
        result = self.run_restore(start=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.read_marker(self.remote_data / "discord_db.sqlite"),
            "snapshot-discord",
        )
        self.assertEqual(
            self.read_marker(self.remote_data / "store_db.sqlite"), "snapshot-store"
        )
        self.assertEqual(self.remote_state.read_text(encoding="utf-8"), "true")

    def test_nonempty_mount_is_never_overwritten(self) -> None:
        marker = self.remote_data / "existing.txt"
        marker.write_text("keep me", encoding="utf-8")

        result = self.run_restore()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Pi /app/data is not empty", result.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")
        self.assertFalse((self.remote_data / "store_db.sqlite").exists())

    def test_changed_snapshot_is_rejected_before_remote_restore(self) -> None:
        (self.snapshot_data / "store_db.sqlite").write_bytes(b"changed")

        result = self.run_restore()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.remote_data.iterdir()), [])
        self.assertEqual(self.remote_state.read_text(encoding="utf-8"), "false")

    def test_partial_transfer_is_removed_and_container_stays_stopped(self) -> None:
        result = self.run_restore(transfer_mode="partial")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.remote_data.iterdir()), [])
        self.assertEqual(self.remote_state.read_text(encoding="utf-8"), "false")
        self.assertIn("Partial Pi restore removed", result.stdout)


if __name__ == "__main__":
    unittest.main()
