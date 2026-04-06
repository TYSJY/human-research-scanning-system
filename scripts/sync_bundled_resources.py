from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

RESOURCE_DIRS = ["configs", "control_plane", "projects", "templates"]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def bundled_root() -> Path:
    return repo_root() / "research_os" / "_resources"


def sync_resources() -> int:
    source = repo_root()
    target = bundled_root()
    target.mkdir(parents=True, exist_ok=True)
    for name in RESOURCE_DIRS:
        src = source / name
        dst = target / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    readme = target / "README.md"
    readme.write_text(
        "# Bundled runtime resources\n\n"
        "This directory is intentionally committed so wheel installs keep working\n"
        "even when the source checkout is not present.\n",
        encoding="utf-8",
    )
    return 0


def check_resources() -> int:
    source = repo_root()
    target = bundled_root()
    missing: list[str] = []
    for name in RESOURCE_DIRS:
        src = source / name
        dst = target / name
        if not dst.exists():
            missing.append(f"missing bundle: {dst}")
            continue
        source_files = sorted(str(p.relative_to(src)) for p in src.rglob('*') if p.is_file())
        bundled_files = sorted(str(p.relative_to(dst)) for p in dst.rglob('*') if p.is_file())
        if source_files != bundled_files:
            missing.append(f"out of sync: {name}")
    if missing:
        print("Bundled resources are not in sync:", file=sys.stderr)
        for item in missing:
            print(f"- {item}", file=sys.stderr)
        return 1
    print("Bundled resources are in sync.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync bundled runtime resources into research_os/_resources")
    parser.add_argument("--check", action="store_true", help="Only verify sync status; do not copy files.")
    args = parser.parse_args(argv)
    return check_resources() if args.check else sync_resources()


if __name__ == "__main__":
    raise SystemExit(main())
