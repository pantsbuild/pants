# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='pants_requirement',
  sources=['test_pants_requirement.py'],
  dependencies=[
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_environment',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='python_chroot',
  sources=['test_python_chroot.py'],
  dependencies=[
    '3rdparty/python:pex',
    'src/python/pants/backend/codegen/targets:python',

    # TODO(John Sirois): XXX this dep needs to be fixed.  All pants/java utility code needs to live
    # in pants java since non-jvm backends depend on it to run things.
    'src/python/pants/backend/jvm/subsystems:jvm',

    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:python_chroot',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/backend/python:python_setup',
    'src/python/pants/binaries:thrift_util',
    'src/python/pants/ivy',
    'src/python/pants/util:contextutil',
    'src/python/pants/source',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='python_requirement_list',
  sources=['test_python_requirement_list.py'],
  dependencies=[
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test'
  ]
)
