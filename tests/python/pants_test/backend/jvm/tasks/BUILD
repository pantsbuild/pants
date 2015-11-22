# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'tasks',
  dependencies = [
    ':benchmark_run',
    ':binary_create',
    ':bootstrap_jvm_tools',
    ':bundle_create',
    ':checkstyle',
    ':classpath_products',
    ':classpath_util',
    ':ivy_imports',
    ':ivy_resolve',
    ':ivy_utils',
    ':jar_publish_unit_test',
    ':junit_run',
    ':jvm_dependency_usage',
    ':jvm_platform_analysis',
    ':jvm_run',
    ':resources_task',
    ':prepare_resources',
    ':prepare_services',
    ':properties',
    ':scalastyle',
    ':unpack_jars',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile',
  ]
)

python_tests(
  name = 'binary_create',
  sources = ['test_binary_create.py'],
  dependencies = [
    ':jvm_binary_task_test_base',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:binary_create',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ]
)

python_tests(
  name = 'bootstrap_jvm_tools',
  sources = ['test_bootstrap_jvm_tools.py'],
  dependencies = [
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:bootstrap_jvm_tools',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ]
)

python_tests(
  name = 'bootstrap_jvm_tools_integration',
  sources = ['test_bootstrap_jvm_tools_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name = 'benchmark_run',
  sources = ['test_benchmark_run.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:benchmark_run',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ]
)

python_tests(
  name = 'benchmark_run_integration',
  sources = ['test_benchmark_run_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name = 'binary_create_integration',
  sources = ['test_binary_create_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'bundle_create',
  sources = ['test_bundle_create.py'],
  dependencies = [
    ':jvm_binary_task_test_base',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:bundle_create',
    'src/python/pants/backend/jvm:jar_dependency_utils',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'checkstyle',
  sources = ['test_checkstyle.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:checkstyle',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'checkstyle_integration',
  sources = ['test_checkstyle_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name = 'classpath_products',
  sources = ['test_classpath_products.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm:repository',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'classpath_util',
  sources = ['test_classpath_util.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/goal:products',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'ivy_imports',
  sources = ['test_ivy_imports.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:ivy_imports',
    'src/python/pants/backend/jvm/tasks:jar_import_products',
    'src/python/pants/backend/jvm:jar_dependency_utils',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
  ]
)

python_tests(
  name = 'ivy_resolve',
  sources = ['test_ivy_resolve.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:ivy_resolve',
    'src/python/pants/invalidation',
    'src/python/pants/backend/jvm:ivy_utils',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ]
)

python_tests(
  name = 'ivy_utils',
  sources = ['test_ivy_utils.py'],
  dependencies = [
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm:ivy_utils',
    'src/python/pants/backend/jvm:jar_dependency_utils',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/ivy',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'jar_publish_unit_test',
  sources = ['test_jar_publish_unit.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:jar_publish',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_library(
  name = 'jvm_binary_task_test_base',
  sources = ['jvm_binary_task_test_base.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm:jar_dependency_utils',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ]
)

python_tests(
  name = 'jvm_dependency_usage',
  sources = ['test_jvm_dependency_usage.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks:jvm_dependency_usage',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/goal:products',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'jvm_dependency_usage_integration',
  sources = ['test_jvm_dependency_usage_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name = 'jvm_platform_analysis',
  sources = ['test_jvm_platform_analysis.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_platform_analysis',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'jvm_platform_analysis_integration',
  sources = ['test_jvm_platform_analysis_integration.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_platform_analysis',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name = 'junit_run',
  sources = ['test_junit_run.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:junit_run',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/goal:products',
    'src/python/pants/ivy',
    'src/python/pants/java/distribution:distribution',
    'src/python/pants/java:executor',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)

python_tests(
  name = 'junit_run_integration',
  sources = ['test_junit_run_integration.py'],
  dependencies = [
    'src/python/pants/java/distribution',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)

python_tests(
  name = 'jvm_run',
  sources = ['test_jvm_run.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_run',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/jvm:jvm_task_test_base',
  ]
)

python_tests(
  name = 'resources_task',
  sources = ['test_resources_task.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks:resources_task',
    'src/python/pants/base:fingerprint_strategy',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'prepare_resources',
  sources = ['test_prepare_resources.py'],
  dependencies = [
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:prepare_resources',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'prepare_services',
  sources = ['test_prepare_services.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:prepare_services',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'properties',
  sources = ['test_properties.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:properties',
  ]
)

python_tests(
  name = 'scalastyle',
  sources = ['test_scalastyle.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:scalastyle',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'scala_repl_integration',
  sources = ['test_scala_repl_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'unpack_jars',
  sources = ['test_unpack_jars.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_import_products',
    'src/python/pants/backend/jvm/tasks:unpack_jars',
    'src/python/pants/backend/jvm:jar_dependency_utils',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)
