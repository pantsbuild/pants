# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    ':pants_requirement',
    ':python_artifact',
    ':python_requirements',
    ':target_types',
    'src/python/pants/backend/python/dependency_inference',
    'src/python/pants/backend/python/rules',
    'src/python/pants/build_graph',
    'src/python/pants/python',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'all_utils',
  sources = ['*.py', '!__init__.py', '!register.py', '!*_test.py'],
  dependencies = [
    ':python_artifact',
    ':python_requirements',
    'src/python/pants/python',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'pants_requirement',
  sources = ['pants_requirement.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/python',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'python_artifact',
  sources = ['python_artifact.py'],
  dependencies = [
    'src/python/pants/base:payload_field',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'python_requirements',
  sources = ['python_requirements.py'],
  tags = {"partially_type_checked"},
)

python_library(
  name="target_types",
  sources=["target_types.py"],
  dependencies = [
    ':python_artifact',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/core',
    'src/python/pants/core/util_rules',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:target',
    'src/python/pants/python',
  ],
  tags={"type_checked"},
)

python_tests(
  name="tests",
  dependencies=[
    ":target_types",
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:target',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
  ],
)
