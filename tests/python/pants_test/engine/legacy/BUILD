# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'address_mapper',
  sources = ['test_address_mapper.py'],
  dependencies = [
    'src/python/pants/base:specs',
    'src/python/pants/bin',
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:address_mapper',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'build_ignore_integration',
  sources = [ 'test_build_ignore_integration.py' ],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:phrases_directory',
    'testprojects/tests/python/pants:constants_only_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'bundle_integration',
  sources = ['test_bundle_integration.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:bundle_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 480,
)

python_tests(
  name = 'changed_integration',
  sources = ['test_changed_integration.py'],
  dependencies = [
    '//:gitignore',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:process_handler',
    'src/python/pants/testutil:git_util',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:python_targets_directory',
    'testprojects/src/python:sources_directory',
    'testprojects/tests/scala/org/pantsbuild/testproject:cp-directories_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 600,
)

python_tests(
  name = 'filesystem_specs_integration',
  sources = ['test_filesystem_specs_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/tests/python:owners_integration_target',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'owners_integration',
  sources = ['test_owners_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/tests/python:owners_integration_target',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'goal_rule_integration',
  sources = [ 'test_goal_rule_integration.py' ],
  dependencies = [
    'tests/python/pants_test/pantsd:pantsd_integration_test_base',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 270,
)

python_tests(
  name = 'dependees_integration',
  sources = ['test_dependees_integration.py'],
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
  sources = ['test_dependencies_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 40,
)

python_tests(
  name = 'filemap_integration',
  sources = ['test_filemap_integration.py'],
  dependencies = [
    'src/python/pants/base:project_tree',
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:sources_directory',
    'testprojects/tests/python/pants:file_sets_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'filedeps_integration',
  sources = ['test_filedeps_integration.py'],
  dependencies = [
    'src/python/pants/base:project_tree',
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 180,
)

python_tests(
  name = 'graph',
  sources = ['test_graph.py'],
  dependencies = [
    'src/python/pants/bin',
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/init',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='graph_integration',
  sources=['test_graph_integration.py'],
  dependencies=[
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:graph',
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
  sources = ['test_list_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/tests/python/pants:build_parsing_directory',
    'testprojects/tests/java/org/pantsbuild:build_parsing_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 180,
)

python_tests(
  name = 'options_parsing',
  sources = ['test_options_parsing.py'],
  dependencies = [
    'src/python/pants/bin',
    'src/python/pants/build_graph',
    'src/python/pants/init',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'parser',
  sources = ['test_parser.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:parser',
    'src/python/pants/engine:parser',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'structs',
  sources = ['test_structs.py'],
  dependencies = [
    'src/python/pants/engine/legacy:structs',
  ],
  tags = {"partially_type_checked"},
)
