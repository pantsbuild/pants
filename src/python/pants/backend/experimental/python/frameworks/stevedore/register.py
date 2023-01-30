# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""A python "framework" that for apps to dynamically load plugins.

See https://github.com/openstack/stevedore for details.
"""

from pants.backend.python.frameworks.stevedore import python_target_dependencies
from pants.backend.python.frameworks.stevedore import rules as stevedore_rules
from pants.backend.python.frameworks.stevedore import setup_py_kwargs, target_types_rules
from pants.backend.python.frameworks.stevedore.target_types import StevedoreExtension

# TODO: add stevedore_namespaces field to python_sources?


def rules():
    return [
        *target_types_rules.rules(),
        *stevedore_rules.rules(),
        *python_target_dependencies.rules(),
        *setup_py_kwargs.rules(),
    ]


def target_types():
    return [StevedoreExtension]
