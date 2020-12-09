# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest

from pants.base.build_environment import get_pants_cachedir
from pants.engine.internals.native import Native
from pants.util.contextutil import environment_as, temporary_file


def test_get_pants_cachedir() -> None:
    assert Native().default_cache_path() == get_pants_cachedir()


class TestBuildEnvironment(unittest.TestCase):
    """Test class for pants.base.build_environment."""

    def test_get_cachedir(self) -> None:
        with environment_as(XDG_CACHE_HOME=""):
            self.assertEqual(os.path.expanduser("~/.cache/pants"), get_pants_cachedir())

    def test_set_cachedir(self) -> None:
        with temporary_file() as temp:
            with environment_as(XDG_CACHE_HOME=temp.name):
                self.assertEqual(os.path.join(temp.name, "pants"), get_pants_cachedir())
