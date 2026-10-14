"""sha256_file cache: reuse only for an unchanged file identity."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark_core import hashing


class HashCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.cache = root / "cache.json"
        self.file = root / "data.nt"
        self.file.write_bytes(b"a" * 1000)
        self.patches = [patch.dict(os.environ, {"KROWN_SHA256_CACHE": str(self.cache)}),
                        patch.object(hashing, "CACHE_MIN_BYTES", 0)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.directory.cleanup()

    def forbid_reading(self, *paths):
        original = Path.open
        forbidden = {str(path) for path in paths}

        def guarded(path, *args, **kwargs):
            if str(path) in forbidden:
                raise AssertionError(f"file was read: {path}")
            return original(path, *args, **kwargs)
        return patch.object(Path, "open", guarded)

    def expected(self):
        return hashlib.sha256(self.file.read_bytes()).hexdigest()

    def test_second_call_uses_cache_without_reading(self):
        expected = self.expected()
        self.assertEqual(hashing.sha256_file(self.file), expected)
        with self.forbid_reading(self.file):
            self.assertEqual(hashing.sha256_file(self.file), expected)

    def test_modified_file_is_hashed_again(self):
        hashing.sha256_file(self.file)
        self.file.write_bytes(b"b" * 1000)
        os.utime(self.file, ns=(1, 2))
        self.assertEqual(hashing.sha256_file(self.file), self.expected())

    def test_replaced_file_is_hashed_again(self):
        hashing.sha256_file(self.file)
        replacement = self.file.with_name("new")
        replacement.write_bytes(b"c" * 1000)
        stat = self.file.stat()
        os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        os.replace(replacement, self.file)  # same size and mtime, new inode
        self.assertEqual(hashing.sha256_file(self.file), self.expected())

    def test_hard_link_shares_the_cached_digest(self):
        digest = hashing.sha256_file(self.file)
        link = self.file.with_name("link.nt")
        os.link(self.file, link)
        with self.forbid_reading(self.file, link):
            self.assertEqual(hashing.sha256_file(link), digest)

    def test_cache_can_be_disabled(self):
        with patch.dict(os.environ, {"KROWN_SHA256_CACHE": "off"}):
            hashing.sha256_file(self.file)
        self.assertFalse(self.cache.exists())

    def test_small_files_are_not_cached(self):
        with patch.object(hashing, "CACHE_MIN_BYTES", 10_000):
            hashing.sha256_file(self.file)
        self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main()
