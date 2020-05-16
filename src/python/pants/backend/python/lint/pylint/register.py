# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter for Python.

See https://pants.readme.io/docs/python-linters-and-formatters and https://www.pylint.org.
"""

from pants.backend.python.lint.pylint import rules as pylint_rules
from pants.backend.python.lint.pylint.plugin_target_type import PylintSourcePlugin
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target as TargetV1


def rules():
    return pylint_rules.rules()


def target_types():
    return [PylintSourcePlugin]


# Dummy v1 target to ensure that v1 tasks can still parse v2 BUILD files.
class LegacyPylintSourcePlugin(TargetV1):
    def __init__(self, sources=(), dependencies=(), **kwargs):
        super().__init__(**kwargs)


def build_file_aliases():
    return BuildFileAliases(targets={PylintSourcePlugin.alias: LegacyPylintSourcePlugin})
