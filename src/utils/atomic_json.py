"""Small atomic JSON persistence primitive for production control snapshots."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def json_update_lock(path: str | Path):
    """Serialize a complete read/modify/write transaction across workers.

    Lock a stable sibling file because replacing the JSON changes its inode.
    Keep the lock file in place so waiting and new writers lock the same file.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.with_name(f".{target.name}.lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_json_atomic(path: str | Path, payload: Any) -> None:
    """Publish a complete JSON document without exposing a partial write.

    A unique temporary file avoids collisions between concurrent writers. The
    final ``os.replace`` is atomic on the local filesystems supported by the
    application, so readers see either the old snapshot or the new snapshot.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
