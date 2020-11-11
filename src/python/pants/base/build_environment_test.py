# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest

from pants.base.build_environment import get_pants_cachedir, get_pants_configdir
from pants.engine.internals.native import Native
from pants.util.contextutil import environment_as, temporary_file


def test_get_pants_cachedir() -> None:
    assert Native().default_cache_path() == get_pants_cachedir()


def test_get_pants_configdir() -> None:
    assert Native().default_config_path() == get_pants_configdir()


class TestBuildEnvironment(unittest.TestCase):
    """Test class for pants.base.build_environment."""

    def test_get_configdir(self) -> None:
        with environment_as(XDG_CONFIG_HOME=""):
            self.assertEqual(os.path.expanduser("~/.config/pants"), get_pants_configdir())

    def test_get_cachedir(self) -> None:
        with environment_as(XDG_CACHE_HOME=""):
            self.assertEqual(os.path.expanduser("~/.cache/pants"), get_pants_cachedir())

    def test_set_configdir(self) -> None:
        with temporary_file() as temp:
            with environment_as(XDG_CONFIG_HOME=temp.name):
                self.assertEqual(os.path.join(temp.name, "pants"), get_pants_configdir())

    def test_set_cachedir(self) -> None:
        with temporary_file() as temp:
            with environment_as(XDG_CACHE_HOME=temp.name):
                self.assertEqual(os.path.join(temp.name, "pants"), get_pants_cachedir())

    def test_expand_home_configdir(self) -> None:
        with environment_as(XDG_CONFIG_HOME="~/somewhere/in/home"):
            self.assertEqual(
                os.path.expanduser(os.path.join("~/somewhere/in/home", "pants")),
                get_pants_configdir(),
            )
