# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core BUILD file symbols for Pants to operate correctly.

These are always activated and cannot be disabled.
"""

import os

from pants.base.build_environment import get_buildroot, pants_version
from pants.build_graph.aliased_target import AliasTargetFactory
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.files import Files
from pants.build_graph.intransitive_dependency import (
    IntransitiveDependencyFactory,
    ProvidedDependencyFactory,
)
from pants.build_graph.prep_command import PrepCommand
from pants.build_graph.remote_sources import RemoteSources
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.build_graph.target_scopes import ScopedDependencyFactory
from pants.util.netrc import Netrc


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
        targets={
            "alias": AliasTargetFactory(),
            "files": Files,
            "prep_command": PrepCommand,
            "resources": Resources,
            "remote_sources": RemoteSources,
            "target": Target,
        },
        objects={"get_buildroot": get_buildroot, "netrc": Netrc, "pants_version": pants_version},
        context_aware_object_factories={
            "buildfile_path": BuildFilePath,
            "intransitive": IntransitiveDependencyFactory,
            "provided": ProvidedDependencyFactory,
            "scoped": ScopedDependencyFactory,
        },
    )
