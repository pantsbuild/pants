# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'build_ignore_integration',
  sources = [ 'build_ignore_integration_test.py' ],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:phrases_directory',
    'testprojects/tests/python/pants:constants_only_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'bundle_integration',
  sources = ['bundle_integration_test.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:bundle_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 900,
)

python_tests(
  name = 'changed_integration',
  sources = ['changed_integration_test.py'],
  dependencies = [
    '//:gitignore',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:git_util',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:python_targets_directory',
    'testprojects/src/python:sources_directory',
    'testprojects/tests/scala/org/pantsbuild/testproject:cp-directories_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 850,
)

python_tests(
  name = 'filesystem_specs_integration',
  sources = ['filesystem_specs_integration_test.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/tests/python:owners_integration_target',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'goal_rule_integration',
  sources = ['goal_rule_integration_test.py'],
  dependencies = [
    'tests/python/pants_test/pantsd:pantsd_integration_test_base',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'testprojects/tests/python/pants:dummies_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 900,
)

python_tests(
  name = 'dependees_integration',
  sources = ['dependees_integration_test.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'examples/src/scala/org/pantsbuild/example:jvm_run_directory',
    'examples/tests/scala/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'dependencies_integration',
  sources = ['dependencies_integration_test.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'filemap_integration',
  sources = ['filemap_integration_test.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:sources_directory',
    'testprojects/tests/python/pants:file_sets_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'filedeps_integration',
  sources = ['filedeps_integration_test.py'],
  dependencies = [
    'src/python/pants/base:project_tree',
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 180,
)

python_tests(
  name='graph_integration',
  sources=['graph_integration_test.py'],
  dependencies=[
    'src/python/pants/option',
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:bundle_directory',
    'testprojects/src/python:no_build_file_directory',
    'testprojects/src/python:sources_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 180,
)

python_tests(
  name = 'list_integration',
  sources = ['list_integration_test.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/tests/python/pants:build_parsing_directory',
    'testprojects/tests/java/org/pantsbuild:build_parsing_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 180,
)

python_tests(
  name = 'prelude_integration',
  sources = [ 'test_prelude_integration.py' ],
  dependencies = [
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)
