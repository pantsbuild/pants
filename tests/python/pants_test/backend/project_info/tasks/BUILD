# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'resolve_jars_test_mixin',
  sources = ['resolve_jars_test_mixin.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'dependencies',
  sources = ['test_dependencies.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/project_info/tasks:dependencies',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/python',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'depmap',
  sources = ['test_depmap.py'],
  coverage = ['pants.backend.project_info.tasks.depmap'],
  dependencies = [
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/project_info/tasks:depmap',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/subsystem',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'export',
  sources = ['test_export.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:scoverage_platform',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/project_info/tasks:export',
    'src/python/pants/backend/project_info/tasks:export_version',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/core/util_rules',
    'src/python/pants/java/distribution',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:osutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'export_integration',
  sources = ['test_export_integration.py'],
  dependencies = [
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/scala/org/pantsbuild/example:scala_with_java_sources_directory',
    'examples/tests/java/org/pantsbuild/example:usethrift_directory',
    'src/python/pants/base:build_environment',
    'src/python/pants/build_graph',
    'src/python/pants/ivy',
    'src/python/pants/java/distribution',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:int-test',
    'testprojects/maven_layout:provided_patching_directory',
    'testprojects/src/java/org/pantsbuild/testproject:exclude_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:unicode_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:ivyclassifier_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:testjvms_directory',
    ':resolve_jars_test_mixin',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 750,
)

python_tests(
  name = 'export_dep_as_jar_integration',
  sources = ['test_export_dep_as_jar_integration.py'],
  dependencies = [
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile/scala:base_compile_integration_test',
    'testprojects/src/java/org/pantsbuild/testproject:extra_jvm_options_directory',
    'examples/src/java/org/pantsbuild/example:javac_directory',
    'examples/src/scala/org/pantsbuild/example:several_scala_targets_directory'
  ],
  tags = {"integration", "partially_type_checked"},
  timeout = 850,
)

python_tests(
  name = 'export_dep_as_jar',
  sources = ['test_export_dep_as_jar.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:scoverage_platform',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/project_info/tasks:export_dep_as_jar',
    'src/python/pants/backend/project_info/tasks:export_version',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/core/util_rules',
    'src/python/pants/java/distribution',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:osutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'filedeps',
  sources = ['test_filedeps.py'],
  dependencies = [
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/project_info/tasks:filedeps',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'idea_plugin',
  sources = ['test_idea_plugin.py'],
  dependencies = [
    'src/python/pants/backend/project_info/tasks:idea_plugin_gen',
    'src/python/pants/engine/internals:native',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'idea_plugin_integration',
  sources = ['test_idea_plugin_integration.py'],
  dependencies = [
    'src/python/pants/backend/project_info/tasks:idea_plugin_gen',
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'testprojects/src/python:sources_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)
