# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.build_environment import get_pants_cachedir, get_pants_configdir
from pants.engine.internals.native import Native


def test_get_pants_cachedir() -> None:
    assert Native().default_cache_path() == get_pants_cachedir()


def test_get_pants_configdir() -> None:
    assert Native().default_config_path() == get_pants_configdir()
