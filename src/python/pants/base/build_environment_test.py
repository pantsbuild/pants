# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.build_environment import get_pants_cachedir
from pants.util.contextutil import environment_as, temporary_file


def test_get_pants_cachedir() -> None:
    with environment_as(XDG_CACHE_HOME=""):
        assert os.path.expanduser("~/.cache/pants") == get_pants_cachedir()
    with temporary_file() as temp, environment_as(XDG_CACHE_HOME=temp.name):
        assert os.path.join(temp.name, "pants") == get_pants_cachedir()
