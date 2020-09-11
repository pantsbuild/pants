# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'scalastyle_integration',
  sources = ['test_scalastyle_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:styleissue_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'changed_target_integration',
  sources = ['test_changed_target_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
    'src/python/pants/testutil:git_util',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout=800,
)

python_tests(
  name = 'bootstrap_jvm_tools_integration',
  sources = ['test_bootstrap_jvm_tools_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 540,
)

python_tests(
  name = 'execution_graph',
  sources = ['test_execution_graph.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:execution_graph',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'clean_all_integration',
  sources = ['test_clean_all_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)

files(
  name = 'jar_publish_resources_directory',
  sources = ['jar_publish_resources/**/*'],
)
