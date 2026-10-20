"""Tests for the stat-keyed file hash cache."""

import hashlib
import os
from unittest import mock

import pytest

from src.services import generation_review
from src.services.generation_review import file_hash


@pytest.fixture(autouse=True)
def clear_file_hash_cache():
    generation_review._file_hash_cached.cache_clear()
    yield
    generation_review._file_hash_cached.cache_clear()


def test_file_hash_matches_plain_sha256(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"short-drama" * 1000)

    assert file_hash(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_repeated_hash_reuses_cached_digest(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"payload")

    with mock.patch("builtins.open", wraps=open) as opened:
        first = file_hash(path)
        second = file_hash(path)

    assert first == second
    assert opened.call_count == 1


def test_hash_invalidates_when_file_signature_changes(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"a" * 64)
    first = file_hash(path)
    stat = path.stat()

    path.write_bytes(b"b" * 64)  # same size, different content
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    second = file_hash(path)
    assert second != first
    assert second == hashlib.sha256(b"b" * 64).hexdigest()
