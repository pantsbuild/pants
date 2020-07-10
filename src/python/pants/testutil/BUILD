# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='testutil_wheel',
  sources=[],
  dependencies=[
    ':int-test-for-export',
    ':test_base',
    ':external_tool_test_base',
    ':goal_rule_test_base',
    ':interpreter_selection_utils',
    'src/python/pants/testutil/engine',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil/subsystem',
  ],
  provides=pants_setup_py(
    name='pantsbuild.pants.testutil',
    description='Test support for writing Pants plugins.',
    namespace_packages=['pants.testutil'],
    additional_classifiers=[
      'Topic :: Software Development :: Testing',
    ]
  )
)

python_library(
  name = 'int-test-for-export',
  sources = ['pants_run_integration_test.py'],
  dependencies = [
    '//:build_root',
    'src/python/pants:entry_point'
  ],
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
  ],
)

python_tests(
  name='tests',
  sources=['*_test.py', '!pants_run_integration_test.py']
)

python_library(
  name = 'test_base',
  sources = ['test_base.py'],
)

python_library(
  name = 'external_tool_test_base',
  sources = ['external_tool_test_base.py'],
)

python_library(
  name = 'goal_rule_test_base',
  sources = ['goal_rule_test_base.py'],
)

python_library(
  name='git_util',
  sources=['git_util.py'],
)

python_library(
  name='interpreter_selection_utils',
  sources=['interpreter_selection_utils.py'],
)

python_library(
  name='retry',
  sources=['retry.py'],
)

python_library(
  name='pexrc_util',
  sources=['pexrc_util.py'],
)

python_library(
  name='process_handler',
  sources=['process_handler.py'],
)

python_library(
  name='process_test_util',
  sources=['process_test_util.py'],
)
