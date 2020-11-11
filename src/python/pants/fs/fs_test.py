# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest
from pathlib import Path

from pants.fs.fs import is_child_of, safe_filename


def test_is_child_of() -> None:
    mock_build_root = Path("/mock/build/root")

    assert is_child_of(Path("/mock/build/root/dist/dir"), mock_build_root)
    assert is_child_of(Path("dist/dir"), mock_build_root)
    assert is_child_of(Path("./dist/dir"), mock_build_root)
    assert is_child_of(Path("../root/dist/dir"), mock_build_root)
    assert is_child_of(Path(""), mock_build_root)
    assert is_child_of(Path("./"), mock_build_root)

    assert not is_child_of(Path("/other/random/directory/root/dist/dir"), mock_build_root)
    assert not is_child_of(Path("../not_root/dist/dir"), mock_build_root)


class SafeFilenameTest(unittest.TestCase):
    class FixedDigest:
        def __init__(self, size):
            self._size = size

        def update(self, value):
            pass

        def hexdigest(self):
            return self._size * "*"

    def test_bad_name(self):
        with self.assertRaises(ValueError):
            safe_filename(os.path.join("more", "than", "a", "name.game"))

    def test_noop(self):
        self.assertEqual("jack.jill", safe_filename("jack", ".jill", max_length=9))
        self.assertEqual("jack.jill", safe_filename("jack", ".jill", max_length=100))

    def test_shorten(self):
        self.assertEqual(
            "**.jill", safe_filename("jack", ".jill", digest=self.FixedDigest(2), max_length=8)
        )

    def test_shorten_readable(self):
        self.assertEqual(
            "j.**.e.jill",
            safe_filename("jackalope", ".jill", digest=self.FixedDigest(2), max_length=11),
        )

    def test_shorten_fail(self):
        with self.assertRaises(ValueError):
            safe_filename("jack", ".beanstalk", digest=self.FixedDigest(3), max_length=12)
