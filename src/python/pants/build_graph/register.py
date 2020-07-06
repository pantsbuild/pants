# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core BUILD file symbols for Pants to operate correctly.

These are always activated and cannot be disabled.
"""

import os

from pants.base.build_environment import get_buildroot, pants_version
from pants.build_graph.build_file_aliases import BuildFileAliases


class BuildFilePath:
    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(self):
        """
        :returns: The absolute path of this BUILD file.
        """
        return os.path.join(get_buildroot(), self._parse_context.rel_path)


def build_file_aliases():
    return BuildFileAliases(
        objects={"get_buildroot": get_buildroot, "pants_version": pants_version},
        context_aware_object_factories={"buildfile_path": BuildFilePath},
    )
