# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  sources = ['*.py', '!*_integration.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:dataclasses',
    'src/python/pants/backend/codegen/antlr/java',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
  ],
  tags = {"partially_type_checked"},
)


python_tests(
  name = 'integration',
  sources = ['*_integration.py'],
  dependencies = [
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'examples/src/java/org/pantsbuild/example:antlr3_directory',
    'examples/src/java/org/pantsbuild/example:antlr4_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 240,
)
