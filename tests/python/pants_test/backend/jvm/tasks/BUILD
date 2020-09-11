# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'missing_jvm_check',
  sources = ['missing_jvm_check.py'],
  dependencies = [
    'src/python/pants/java/distribution',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name = 'binary_create',
  sources = ['test_binary_create.py'],
  dependencies = [
    ':jvm_binary_task_test_base',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:binary_create',
    'src/python/pants/java/jar',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/jvm:jvm_tool_task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'bootstrap_jvm_tools',
  sources = ['test_bootstrap_jvm_tools.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:bootstrap_jvm_tools',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/java/distribution',
    'src/python/pants/java/jar',
    'src/python/pants/java:executor',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/jvm:jvm_tool_task_test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'bootstrap_jvm_tools_integration',
  sources = ['test_bootstrap_jvm_tools_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'benchmark_run',
  sources = ['test_benchmark_run.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:benchmark_run',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/testutil/jvm:jvm_tool_task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'benchmark_run_integration',
  sources = ['test_benchmark_run_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:bench_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 500,
)

python_tests(
  name = 'binary_create_integration',
  sources = ['test_binary_create_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
    'examples/src/java/org/pantsbuild/example:autovalue_directory',
    'testprojects/src/java/org/pantsbuild/testproject:deployexcludes_directory',
    'testprojects/src/java/org/pantsbuild/testproject:manifest_directory',
  ],
  timeout=960,
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'bundle_create',
  sources = ['test_bundle_create.py'],
  dependencies = [
    ':jvm_binary_task_test_base',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:bundle_create',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/java/jar',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'consolidate_classpath',
  sources = ['test_consolidate_classpath.py'],
  dependencies = [
    ':jvm_binary_task_test_base',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:consolidate_classpath',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/java/jar',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'checkstyle',
  sources = ['test_checkstyle.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:checkstyle',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'checkstyle_integration',
  sources = ['test_checkstyle_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'testprojects/3rdparty:checkstyle_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 600,
)

python_tests(
  name = 'check_published_deps',
  sources = ['test_check_published_deps.py'],
  dependencies = [
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm:repository',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:check_published_deps',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'classpath_products',
  sources = ['test_classpath_products.py'],
  dependencies = [
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm:repository',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:file_test_util',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'classpath_util',
  sources = ['test_classpath_util.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/goal:products',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jar_dependency_management_setup',
  sources = ['test_jar_dependency_management_setup.py'],
  dependencies = [
    ':jvm_binary_task_test_base',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/subsystems:jar_dependency_management',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:exceptions',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/jvm:jvm_task_test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'detect_duplicates',
  sources = ['test_detect_duplicates.py'],
  dependencies = [
    ':jvm_binary_task_test_base',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:detect_duplicates',
    'src/python/pants/base:exceptions',
    'src/python/pants/java/jar',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'intransitive_integration',
  sources = ['test_intransitive_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:intransitive_directory',
  ],
  timeout=600,
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'ivy_imports',
  sources = ['test_ivy_imports.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:ivy_imports',
    'src/python/pants/backend/jvm/tasks:jar_import_products',
    'src/python/pants/java/jar',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'ivy_outdated_integration',
  sources = ['test_ivy_outdated_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'coursier_resolve',
  sources = ['test_coursier_resolve.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:jar_dependency_management',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:coursier_resolve',
    'src/python/pants/backend/jvm:ivy_utils',
    'src/python/pants/java/jar',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/jvm:jvm_tool_task_test_base',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'coursier_resolve_integration',
  sources = ['test_coursier_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'examples/tests/scala/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'ivy_utils',
  sources = ['test_ivy_utils.py'],
  dependencies = [
    'src/python/pants/backend/jvm:ivy_utils',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm/subsystems:jar_dependency_management',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/build_graph',
    'src/python/pants/ivy',
    'src/python/pants/java/jar',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:ordered_set',
    'tests/python/pants_test/backend/jvm/tasks/ivy_utils_resources',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jar_create',
  sources = ['test_jar_create.py'],
  dependencies = [
    'src/python/pants/backend/codegen/thrift/java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:jar_create',
    'src/python/pants/base:build_environment',
    'src/python/pants/build_graph',
    'src/python/pants/java/jar',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/base:context_utils',
    'src/python/pants/testutil/jvm:jar_task_test_base',
    'src/python/pants/testutil:task_test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jar_publish',
  sources = ['test_jar_publish.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_publish',
    'src/python/pants/base:generator',
    'src/python/pants/build_graph',
    'src/python/pants/scm:scm',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil:mock_logger',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jar_publish_integration',
  sources = ['test_jar_publish_integration.py'],
  dependencies = [
    'examples/src/python/example:pants_publish_plugin_directory',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
    'tests/python/pants_test/tasks:jar_publish_resources_directory',
    'testprojects/src/java/org/pantsbuild/testproject:publish_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:publish_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 480,
)

python_tests(
  name = 'jar_task',
  sources = ['test_jar_task.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_task',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/jvm:jar_task_test_base',
    'src/python/pants/testutil/jvm:jvm_tool_task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'junit_run',
  sources = ['test_junit_run.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:junit_run',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/goal:products',
    'src/python/pants/ivy',
    'src/python/pants/java/distribution:distribution',
    'src/python/pants/java:executor',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/jvm:jvm_tool_task_test_base',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {'partially_type_checked'},
  timeout = 450,
)

python_tests(
  name = 'junit_run_integration',
  sources = ['test_junit_run_integration.py'],
  dependencies = [
    ':missing_jvm_check',
    'examples/tests/scala/org/pantsbuild/example:hello_directory',
    'src/python/pants/base:build_environment',
    'src/python/pants/testutil:int-test',
    'testprojects/tests/java/org/pantsbuild/testproject:coverage_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:cucumber_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:dummies_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:htmlreport_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:matcher_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:syntheticjar_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:testjvms_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:timeout_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:unicode_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 600
)

python_tests(
  name = 'junit_tests_integration',
  sources = ['test_junit_tests_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'examples/tests/java/org/pantsbuild/example:hello_directory',
    'examples/tests/scala/org/pantsbuild/example:hello_directory',
    'testprojects/maven_layout:junit_resource_collision_directory',
    'testprojects/src/java/org/pantsbuild/testproject:junit_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:annotation_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:cwdexample_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:dummies_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:fail256_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:workdirs_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 1240,
)

python_tests(
  name = 'junit_tests_concurrency_integration',
  sources = ['test_junit_tests_concurrency_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'testprojects/tests/java/org/pantsbuild/testproject:parallel_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:parallelclassesandmethods_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:parallelmethods_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 540,
)

python_library(
  name = 'jvm_binary_task_test_base',
  sources = ['jvm_binary_task_test_base.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/java/jar',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jvm_bundle_integration',
  sources = ['test_jvm_bundle_integration.py'],
  dependencies = [
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'testprojects/maven_layout:resource_collision_directory',
    'testprojects/src/java/org/pantsbuild/testproject:unicode_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 600,
)

python_tests(
  name = 'jvm_dependency_usage',
  sources = ['test_jvm_dependency_usage.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks:jvm_dependency_usage',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jvm_dependency_usage_integration',
  sources = ['test_jvm_dependency_usage_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:nocache_directory',
    'testprojects/src/java/org/pantsbuild/testproject:unicode_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 700,
)

python_tests(
  name = 'jvm_platform_analysis',
  sources = ['test_jvm_platform_analysis.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_platform_analysis',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jvm_platform_analysis_integration',
  sources = ['test_jvm_platform_analysis_integration.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_platform_analysis',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'jvm_prep_command',
  sources = ['test_jvm_prep_command.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:run_jvm_prep_command',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jvm_prep_command_integration',
  sources = ['test_jvm_prep_command_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:jvmprepcommand_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 600,
)

python_tests(
  name = 'jvm_task',
  sources = ['test_jvm_task.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks:jvm_task',
    'src/python/pants/testutil/jvm:jvm_task_test_base',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jvm_run',
  sources = ['test_jvm_run.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:jvm',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_run',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/jvm:jvm_task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jvm_run_integration',
  sources = ['test_jvm_run_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/maven_layout:resource_collision_directory',
    'testprojects/src/java/org/pantsbuild/testproject:cwdexample_directory',
    'testprojects/src/java/org/pantsbuild/testproject:extra_jvm_options_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:syntheticjar_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 360,
)

python_tests(
  name = 'jvmdoc_gen',
  sources = ['test_jvmdoc_gen.py'],
  dependencies = [
    ':jvmdoc_gen_testdata',
    'src/python/pants/backend/jvm/tasks:jvmdoc_gen',
    'src/python/pants/base:exceptions',
    'src/python/pants/testutil/jvm:jvm_task_test_base'
  ],
  tags = {"partially_type_checked"},
)

resources(
  name='jvmdoc_gen_testdata',
  sources = ['false.py', 'true.py'],
)

python_tests(
  name = 'resources_task',
  sources = ['test_resources_task.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks:resources_task',
    'src/python/pants/base:fingerprint_strategy',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'prepare_resources',
  sources = ['test_prepare_resources.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:prepare_resources',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'prepare_services',
  sources = ['test_prepare_services.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:prepare_services',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'properties',
  sources = ['test_properties.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:properties',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'scalafmt',
  sources = ['test_scalafmt.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:scoverage_platform',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:scalafmt',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil/subsystem'
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'scalafix',
  sources = ['test_scalafix.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:scalafix',
    'src/python/pants/testutil:int-test',
    'testprojects/src/scala/org/pantsbuild/testproject:procedure_syntax_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:rsc_compat_directory',
  ],
  timeout=800,
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'scalastyle',
  sources = ['test_scalastyle.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:scoverage_platform',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:scalastyle',
    'src/python/pants/base:exceptions',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'scala_repl_integration',
  sources = ['test_scala_repl_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:unicode_directory',
  ],
  timeout=800,
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'scope_provided_integration',
  sources = ['test_scope_provided_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/maven_layout:provided_patching_directory',
    'testprojects/src/java/org/pantsbuild/testproject:provided_directory',
  ],
  timeout=900,
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'scope_runtime_integration',
  sources = ['test_scope_runtime_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:runtime_directory',
  ],
  timeout=900,
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'scope_test_integration',
  sources = ['test_scope_test_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:junit_directory',
  ],
  timeout=700,
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'unpack_jars',
  sources = ['test_unpack_jars.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_import_products',
    'src/python/pants/backend/jvm/tasks:unpack_jars',
    'src/python/pants/java/jar',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'export_classpath_integration',
  sources = ['test_export_classpath_integration.py'],
  dependencies = [
    'src/python/pants/testutil:task_test_base',
    'src/python/pants/testutil:int-test',
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'testprojects/src/java/org/pantsbuild/testproject:exclude_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 600
)

python_tests(
  name = 'classmap',
  sources = ['test_classmap.py'],
  dependencies = [
    ':jvm_binary_task_test_base',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:classmap',
    'src/python/pants/java/jar',
    'src/python/pants/testutil/jvm:jvm_task_test_base',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'classmap_integration',
  sources = ['test_classmap_integration.py'],
  dependencies = [
    'src/python/pants/testutil:task_test_base',
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:unicode_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:testjvms_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 800,
)

python_tests(
  name = 'nailgun_task',
  sources = ['test_nailgun_task.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/java:nailgun_executor',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/jvm:jvm_tool_task_test_base',
  ],
  tags = {"partially_type_checked"},
)
