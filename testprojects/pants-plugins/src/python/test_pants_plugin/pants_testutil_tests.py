# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from test_pants_plugin.subsystems.pants_testutil_subsystem import PantsTestutilSubsystem

from pants.backend.python.targets.python_tests import PythonTests


class PantsTestutilTests:
    def __init__(self, parse_context):
        self._parse_context = parse_context
        self._pants_test_util = PantsTestutilSubsystem.global_instance()

    def __call__(self, dependencies=[], **kwargs):
        dependencies.extend(self._pants_test_util.dependent_target_addrs())
        self._parse_context.create_object(PythonTests.alias(), dependencies=dependencies, **kwargs)
