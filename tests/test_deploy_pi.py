import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = PROJECT_ROOT / "scripts" / "deploy_pi.sh"


class DeployPiScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.root = Path(self.temp_directory.name)

        self.repo = self.root / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        self.script = self.repo / "scripts" / "deploy_pi.sh"
        shutil.copy2(DEPLOY_SCRIPT, self.script)
        self.script.chmod(0o755)

        for relative_path in (
            ".env",
            "docker-compose.yml",
            "bot/config/settings.json",
            "bot/config/welcome_messages.txt",
            "store_data_extractor/config/stores.json",
            "store_data_extractor/config/user_agents.txt",
        ):
            path = self.repo / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("test\n", encoding="utf-8")

        self.event_log = self.root / "events.log"
        self.mock_bin = self.root / "mock-bin"
        self.mock_bin.mkdir()
        self.write_mock_commands()

        backup_mock = self.repo / "scripts" / "backup_pi_data.sh"
        backup_mock.write_text(
            "#!/usr/bin/env bash\nprintf 'backup\\n' >> \"$FAKE_EVENT_LOG\"\n",
            encoding="utf-8",
        )
        backup_mock.chmod(0o755)

    def write_mock_commands(self) -> None:
        docker_mock = self.mock_bin / "docker"
        docker_mock.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                printf 'local-docker:%s\n' "$*" >> "$FAKE_EVENT_LOG"
                case "$*" in
                  info|"buildx version"|"buildx build"*) exit 0 ;;
                  "save discord-bot:latest") printf 'fake image archive' ;;
                  *) exit 64 ;;
                esac
                """
            ),
            encoding="utf-8",
        )
        docker_mock.chmod(0o755)

        ssh_mock = self.mock_bin / "ssh"
        ssh_mock.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                remote_command="${!#}"
                case "$remote_command" in
                  true) exit 0 ;;
                  "uname -m") printf 'aarch64\n' ;;
                  *"command -v docker"*) exit 0 ;;
                  *"mkdir -p"*"&& pwd"*) printf '/home/pi/programs/jirai_sweeties\n' ;;
                  *"docker inspect 'discord-bot' >/dev/null"*)
                    [ "$FAKE_CONTAINER_EXISTS" = true ]
                    ;;
                  *"test -f"*"discord_db.sqlite"*"store_db.sqlite"*)
                    [ "$FAKE_REMOTE_DATABASES_EXIST" = true ]
                    ;;
                  *"range .Mounts"*)
                    printf '%s\n' "$FAKE_MOUNT_TYPE"
                    printf '%s\n' "$FAKE_MOUNT_SOURCE"
                    ;;
                  *"docker image load"*)
                    printf 'remote:image-load\n' >> "$FAKE_EVENT_LOG"
                    ;;
                  *"docker compose down"*)
                    printf 'remote:compose-down\n' >> "$FAKE_EVENT_LOG"
                    ;;
                  *"cp -a data"*)
                    printf 'remote:rollback-copy\n' >> "$FAKE_EVENT_LOG"
                    ;;
                  *"docker compose up"*)
                    printf 'remote:compose-up\n' >> "$FAKE_EVENT_LOG"
                    ;;
                  *"{{.State.Running}}"*) printf 'true\n' ;;
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

        for command_name, contents in {
            "scp": "printf 'scp\\n' >> \"$FAKE_EVENT_LOG\"\n",
            "sleep": ":\n",
        }.items():
            command = self.mock_bin / command_name
            command.write_text(
                f"#!/usr/bin/env bash\nset -euo pipefail\n{contents}",
                encoding="utf-8",
            )
            command.chmod(0o755)

    def run_deploy(
        self,
        *,
        mount_type: str = "bind",
        mount_source: str = "/home/pi/programs/jirai_sweeties/data",
        container_exists: bool = True,
        remote_databases_exist: bool = True,
    ) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.mock_bin}:{environment['PATH']}",
                "PI_HOST": "pi.test",
                "PI_USER": "pi",
                "PI_DIR": "programs/jirai_sweeties",
                "FAKE_EVENT_LOG": str(self.event_log),
                "FAKE_MOUNT_TYPE": mount_type,
                "FAKE_MOUNT_SOURCE": mount_source,
                "FAKE_CONTAINER_EXISTS": str(container_exists).lower(),
                "FAKE_REMOTE_DATABASES_EXIST": str(remote_databases_exist).lower(),
            }
        )
        return subprocess.run(
            [str(self.script)],
            cwd=self.repo,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def events(self) -> list[str]:
        if not self.event_log.exists():
            return []
        return self.event_log.read_text(encoding="utf-8").splitlines()

    def test_legacy_named_volume_is_snapshotted_then_deploy_is_refused(self) -> None:
        result = self.run_deploy(
            mount_type="volume",
            mount_source="/var/lib/docker/volumes/discord-bot-data/_data",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing deploy", result.stderr)
        self.assertIn("backup", self.events())
        self.assertFalse(
            any(event.startswith("local-docker:buildx build") for event in self.events())
        )
        self.assertNotIn("remote:compose-down", self.events())

    def test_canonical_bind_mount_is_backed_up_before_default_keep_deploy(self) -> None:
        result = self.run_deploy(
            mount_type="bind",
            mount_source="/home/pi/programs/jirai_sweeties/data",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        events = self.events()
        self.assertLess(events.index("backup"), events.index("remote:compose-down"))
        self.assertIn("Keeping both Pi databases", result.stdout)
        self.assertIn("remote:rollback-copy", events)
        self.assertIn("remote:compose-up", events)

    def test_reinstall_without_restored_databases_is_refused_before_build(self) -> None:
        result = self.run_deploy(
            container_exists=False,
            remote_databases_exist=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("restore a snapshot before deploy", result.stderr)
        self.assertNotIn("backup", self.events())
        self.assertFalse(
            any(event.startswith("local-docker:buildx build") for event in self.events())
        )
        self.assertNotIn("remote:compose-up", self.events())


if __name__ == "__main__":
    unittest.main()
