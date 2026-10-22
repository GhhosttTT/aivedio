#!/usr/bin/env python3
"""List or delete storage files older than a retention window.

Dry-run is the default; pass --apply to actually delete. The script never
follows paths outside the configured storage root.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings  # noqa: E402
from src.utils.storage import StorageManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="retention days (default: 30)")
    parser.add_argument("--path", default=None, help="storage root (default: STORAGE_PATH)")
    parser.add_argument("--apply", action="store_true", help="delete files instead of listing")
    parser.add_argument("--limit", type=int, default=10, help="files to show during dry run (default: 10)")
    args = parser.parse_args()
    if args.days < 0:
        parser.error("--days must be non-negative")
    if args.limit < 0:
        parser.error("--limit must be non-negative")

    storage_path = Path(args.path or settings.STORAGE_PATH)
    if not storage_path.is_dir():
        print(f"storage root does not exist: {storage_path}", file=sys.stderr)
        return 2
    manager = StorageManager(base_path=storage_path)
    old_files = manager.find_old_files(args.days)
    total_bytes = 0
    for path in old_files:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
    print(
        f"storage root: {manager.base_path}\n"
        f"files older than {args.days}d: {len(old_files)} "
        f"({total_bytes / (1024 * 1024):.1f} MiB)"
    )
    if not args.apply:
        for path in old_files[: args.limit]:
            try:
                relative = path.relative_to(manager.base_path)
            except ValueError:
                relative = path
            print(f"  {relative}")
        if len(old_files) > args.limit:
            print(f"  ... and {len(old_files) - args.limit} more")
        print("dry run; add --apply to delete")
        return 0
    print(f"deleted: {manager.cleanup_old_files(args.days)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
