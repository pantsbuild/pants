# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, MultipleSourcesField, Target


class HelmUnitTestDependenciesField(Dependencies):
    pass


# -----------------------------------------------------------------------------------------------
# `helm_unittests` target generator
# -----------------------------------------------------------------------------------------------


class HelmUnitTestSourcesField(MultipleSourcesField):
    default = ("*_test.yaml", "*_test.yml")
    expected_file_extensions = (".yaml", ".yml")


class HelmUnitTestsTarget(Target):
    alias = "helm_unittest_tests"
    core_fields = (*COMMON_TARGET_FIELDS, HelmUnitTestSourcesField, HelmUnitTestDependenciesField)
    help = "Generate a `helm_unittest` target for each file in the `sources` field"
