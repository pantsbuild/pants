# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import os
import random
import stat
import unittest
import unittest.mock

from pants.util.contextutil import temporary_dir, temporary_file, temporary_file_path
from pants.util.fileutil import (
    atomic_copy,
    create_size_estimators,
    safe_hardlink_or_copy,
    safe_temp_edit,
)


class FileutilTest(unittest.TestCase):
    def test_atomic_copy(self) -> None:
        with temporary_file() as src:
            src.write(src.name.encode())
            src.flush()
            with temporary_file() as dst:
                atomic_copy(src.name, dst.name)
                dst.close()
                with open(dst.name, "r") as new_dst:
                    self.assertEqual(src.name, new_dst.read())
                self.assertEqual(os.stat(src.name).st_mode, os.stat(dst.name).st_mode)

    def test_line_count_estimator(self) -> None:
        with temporary_file_path() as src:
            self.assertEqual(create_size_estimators()["linecount"]([src]), 0)

    def test_random_estimator(self) -> None:
        seedValue = 5
        # The number chosen for seedValue doesn't matter, so long as it is the same for the call to
        # generate a random test number and the call to create_size_estimators.
        random.seed(seedValue)
        rand = random.randint(0, 10000)
        random.seed(seedValue)
        with temporary_file_path() as src:
            self.assertEqual(create_size_estimators()["random"]([src]), rand)

    @classmethod
    def _is_hard_link(cls, filename: str, other: str) -> bool:
        s1 = os.stat(filename)
        s2 = os.stat(other)
        return (s1[stat.ST_INO], s1[stat.ST_DEV]) == (s2[stat.ST_INO], s2[stat.ST_DEV])

    def test_hardlink_or_copy(self) -> None:
        content = b"hello"

        with temporary_dir() as src_dir, temporary_file() as dst:
            dst.write(content)
            dst.close()

            src_path = os.path.join(src_dir, "src")
            safe_hardlink_or_copy(dst.name, src_path)

            with open(src_path, "rb") as f:
                self.assertEqual(content, f.read())

            # Make sure it's not symlink
            self.assertFalse(os.path.islink(dst.name))

            # Make sure they point to the same node
            self.assertTrue(self._is_hard_link(dst.name, src_path))

    def test_hardlink_or_copy_cross_device_should_copy(self) -> None:
        content = b"hello"

        # Mock os.link to throw an CROSS-DEVICE error
        with unittest.mock.patch("os.link") as os_mock:
            err = OSError()
            err.errno = errno.EXDEV
            os_mock.side_effect = err

            with temporary_dir() as src_dir, temporary_file() as dst:
                dst.write(content)
                dst.close()

                src_path = os.path.join(src_dir, "src")

                safe_hardlink_or_copy(dst.name, src_path)

                with open(src_path, "rb") as f:
                    self.assertEqual(content, f.read())

                # Make sure it's not symlink
                self.assertFalse(os.path.islink(dst.name))

                # Make sure they are separate copies
                self.assertFalse(self._is_hard_link(dst.name, src_path))

    def test_safe_temp_edit(self) -> None:
        content = b"hello"

        with temporary_file() as temp_file:
            temp_file.write(content)
            temp_file.close()

            with open(temp_file.name, "rb") as f:
                self.assertEqual(content, f.read())

            temp_content = b"hello world"
            with safe_temp_edit(temp_file.name) as temp_edit_file:
                with open(temp_edit_file, "wb") as t_f:
                    t_f.write(temp_content)

                # Make sure the edit is actually happening in temp_file
                with open(temp_file.name, "rb") as f:
                    self.assertEqual(temp_content, f.read())

            # Test that temp_file has been safely recovered.
            with open(temp_file.name, "rb") as f:
                self.assertEqual(content, f.read())
