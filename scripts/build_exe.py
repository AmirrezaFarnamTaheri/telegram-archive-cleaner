"""Build script to compile Telegram Archive Cleaner into a single-file Windows executable."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def build() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    spec_file = repo_root / "telegram-archive-cleaner.spec"

    print("Building standalone executable with PyInstaller...")
    print(f"Project root: {repo_root}")
    print(f"Spec file: {spec_file}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file),
    ]

    result = subprocess.run(cmd, cwd=str(repo_root))
    if result.returncode != 0:
        print(f"Build failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    exe_path = repo_root / "dist" / "TelegramArchiveCleaner.exe"
    if exe_path.is_file():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print("Build succeeded! Standalone executable created at:")
        print(f"  -> {exe_path} ({size_mb:.2f} MB)")
    else:
        print("Warning: Output binary not found at expected path.")


if __name__ == "__main__":
    build()
