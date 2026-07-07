from pathlib import Path
import compileall


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    "bot",
    "store_data_extractor",
    "utils",
    "main_file.py",
    "run.py",
]


def main() -> None:
    success = True

    for target in TARGETS:
        path = PROJECT_ROOT / target
        if path.is_dir():
            success = compileall.compile_dir(str(path), quiet=1) and success
        else:
            success = compileall.compile_file(str(path), quiet=1) and success

    if not success:
        raise SystemExit(1)

    print("compile smoke passed")


if __name__ == "__main__":
    main()
