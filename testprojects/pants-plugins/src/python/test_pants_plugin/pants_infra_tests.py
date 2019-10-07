# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from test_pants_plugin.subsystems.pants_test_infra import PantsTestInfra

from pants.backend.python.targets.python_tests import PythonTests


class PantsInfraTests:
    def __init__(self, parse_context):
        self._parse_context = parse_context
        self._pants_test_infra = PantsTestInfra.global_instance()

    def __call__(self, dependencies=[], **kwargs):
        dependencies.extend(self._pants_test_infra.dependent_target_addrs())
        self._parse_context.create_object(PythonTests.alias(), dependencies=dependencies, **kwargs)
