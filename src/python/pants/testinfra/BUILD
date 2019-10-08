# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='test_infra',
  dependencies=[
    ':legacy_test_infra',
    ':int-test-for-export',
    ':test_base',
    'src/python/pants/testinfra/jvm:jar_task_test_base',
    'src/python/pants/testinfra/jvm:nailgun_task_test_base',
    'src/python/pants/testinfra/jvm:jvm_tool_task_test_base',
    'src/python/pants/testinfra/engine:engine_test_base',
    'src/python/pants/testinfra/subsystem',
  ],
  provides=pants_setup_py(
    name='pantsbuild.pants.testinfra',
    description='Test support for writing pants plugins.',
    namespace_packages=['pants.testinfra', 'pants_test'],
    additional_classifiers=[
      'Topic :: Software Development :: Testing',
    ]
  )
)

# NB: The below targets are only here to ensure that we still include in the wheel the original
# pants_test files. We add all transitive dependencies on testinfra code explicitly.
# These should be deleted once we can remove the files.
python_library(
  name='legacy_test_infra',
  dependencies=[
    'tests/python/pants_test:int-test-for-export',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/jvm:jar_task_test_base',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
    'tests/python/pants_test/engine:engine_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/base:context_utils',
    'tests/python/pants_test/engine:util',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test/testutils:file_test_util',
  ],
)

python_library(
  name = 'int-test-for-export',
  sources = [
    'pants_run_integration_test.py'
  ],
  dependencies = [
    '//:build_root',
    '//:pants_pex',
    '3rdparty/python:ansicolors',
    '3rdparty/python:dataclasses',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file',
    'src/python/pants/base:exiter',
    'src/python/pants/fs',
    'src/python/pants/subsystem',
    'src/python/pants/testinfra/utils:file_test_util',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:osutil',
    'src/python/pants/util:process_handler',
    'src/python/pants/util:strutil',
    'src/python/pants:entry_point',
  ]
)

target(
  name = 'int-test',
  dependencies=[
    ':int-test-for-export',
    # NB: 'pants_run_integration_test.py' runs ./pants in a subprocess, so test results will depend
    # on the pants binary and all of its transitive dependencies. Adding the dependencies below is
    # our best proxy for ensuring that any test target depending on this target will be invalidated
    # on changes to those undeclared dependencies.
    'src/python/pants/bin:pants_local_binary',
    'src/rust/engine',
    '//:pyproject',
  ],
)


python_library(
  name = 'test_base',
  sources = ['test_base.py'],
  dependencies = [
    'src/python/pants/base:build_root',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/init',
    'src/python/pants/source',
    'src/python/pants/subsystem',
    'src/python/pants/task',
    'src/python/pants/testinfra/base:context_utils',
    'src/python/pants/testinfra/engine:util',
    'src/python/pants/testinfra/option',
    'src/python/pants/testinfra/subsystem',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name = 'console_rule_test_base',
  sources = ['console_rule_test_base.py'],
  dependencies = [
    ':test_base',
    'src/python/pants/bin',
    'src/python/pants/init',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name = 'task_test_base',
  sources = ['task_test_base.py'],
  dependencies = [
    'src/python/pants/goal:context',
    'src/python/pants/ivy',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:meta',
    'src/python/pants/util:memo',
    'src/python/pants/util:objects',
    ':test_base',
  ]
)

python_library(
  name='interpreter_selection_utils',
  sources=['interpreter_selection_utils.py'],
)
