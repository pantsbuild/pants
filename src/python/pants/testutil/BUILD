# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='testutil_wheel',
  dependencies=[
    ':int-test-for-export',
    ':test_base',
    'src/python/pants/testutil/base:context_utils',
    'src/python/pants/testutil/engine',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {'partially_type_checked'},
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
    '//:pants_pex',
    ':file_test_util',
    '3rdparty/python:ansicolors',
    '3rdparty/python:dataclasses',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exiter',
    'src/python/pants/build_graph:address',
    'src/python/pants/fs',
    'src/python/pants/option',
    'src/python/pants/pantsd:pants_daemon_client',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:osutil',
    'src/python/pants/util:process_handler',
    'src/python/pants/util:strutil',
    'src/python/pants:entry_point',
  ],
  tags = {'partially_type_checked'},
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


python_library(
  name = 'test_base',
  sources = ['test_base.py'],
  dependencies = [
    'src/python/pants/base:build_root',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/init',
    'src/python/pants/option:global_options',
    'src/python/pants/option:options_bootstrapper',
    'src/python/pants/source',
    'src/python/pants/subsystem',
    'src/python/pants/task',
    'src/python/pants/testutil/base:context_utils',
    'src/python/pants/testutil/engine',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'external_tool_test_base',
  sources = ['external_tool_test_base.py'],
  dependencies = [
    ':test_base',
    'src/python/pants/core/util_rules',
  ],
  tags = {"partially_type_checked"},
)


python_library(
  name = 'goal_rule_test_base',
  sources = ['goal_rule_test_base.py'],
  dependencies = [
    ':test_base',
    '3rdparty/python:dataclasses',
    'src/python/pants/init',
    'src/python/pants/testutil/option',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='git_util',
  sources=['git_util.py'],
  dependencies = [
    'src/python/pants/base:revision',
    'src/python/pants/scm',
    'src/python/pants/util:contextutil',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='interpreter_selection_utils',
  sources=['interpreter_selection_utils.py'],
  tags = {"partially_type_checked"},
)

python_library(
  name='retry',
  sources=['retry.py'],
  tags = {"partially_type_checked"},
)

python_library(
  name='pexrc_util',
  sources=['pexrc_util.py'],
  dependencies = [
    ':git_util',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='process_test_util',
  sources=['process_test_util.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    '3rdparty/python:psutil',
  ],
  tags = {"partially_type_checked"},
)
