# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""A python "framework" for apps to dynamically load plugins.

See https://github.com/openstack/stevedore for details.
"""

from pants.backend.python.framework.stevedore import python_target_dependencies
from pants.backend.python.framework.stevedore import rules as stevedore_rules
from pants.backend.python.framework.stevedore.target_types import StevedoreNamespace
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.backend.python.util_rules.entry_points import rules as entry_points_rules
from pants.build_graph.build_file_aliases import BuildFileAliases


def build_file_aliases():
    return BuildFileAliases(objects={StevedoreNamespace.alias: StevedoreNamespace})


def rules():
    return [
        *entry_points_rules(),
        *stevedore_rules.rules(),
        *python_target_dependencies.rules(),
        *python_target_types_rules(),
    ]
