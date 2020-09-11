# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'address',
  sources = ['test_address.py'],
  dependencies = [
    'src/python/pants/base:build_root',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'build_configuration',
  sources = ['test_build_configuration.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:unions',
    'src/python/pants/engine/internals:native',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'subproject_integration',
  sources = ['test_subproject_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)


python_tests(
  name = 'build_file_aliases',
  sources = ['test_build_file_aliases.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/util:frozendict',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  sources = ['test_build_graph.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base'
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'build_graph_integration',
  sources = ['test_build_graph_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:cycle1_directory',
    'testprojects/src/java/org/pantsbuild/testproject:cycle2_directory',
    'testprojects/src/python:build_file_imports_function_directory',
    'testprojects/src/python:build_file_imports_module_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 150,
)

python_tests(
  name = 'intermediate_target_integration',
  sources = ['test_intermediate_target_integration.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/testutil:int-test',
    'testprojects/maven_layout:provided_patching_directory',
    'testprojects/src/java/org/pantsbuild/testproject:intransitive_directory',
    'testprojects/src/java/org/pantsbuild/testproject:runtime_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'scopes',
  sources = ['test_scopes.py'],
  dependencies = [
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'source_mapper',
  sources = ['test_source_mapper.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'target',
  sources = ['test_target.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/base:fingerprint_strategy',
    'src/python/pants/base:payload',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'files',
  sources = ['test_files.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'target_filter_subsystem',
  sources = ['test_target_filter_subsystem.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)
