# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='shader',
  sources=['test_shader.py'],
  dependencies=[
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='custom_scala',
  sources=['test_custom_scala.py'],
  dependencies=[
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:scoverage_platform',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:scalastyle',
    'src/python/pants/backend/jvm/tasks/jvm_compile/zinc',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)


python_tests(
  name='test_scoverage_platform',
  sources=['test_scoverage_platform.py'],
  dependencies=[
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:scoverage_platform',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:scalastyle',
    'src/python/pants/backend/jvm/tasks/jvm_compile/zinc',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='incomplete_custom_scala',
  sources=['test_incomplete_custom_scala.py'],
  dependencies=[
    'src/python/pants/util:dirutil',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'testprojects/src/scala/org/pantsbuild/testproject:custom_scala_platform_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout=900,
)

python_tests(
  name='shader_integration',
  sources=['test_shader_integration.py'],
  dependencies=[
    'src/python/pants/fs',
    'src/python/pants/java/distribution',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:shading_directory',
    'testprojects/3rdparty:managed_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 800,
)

python_tests(
  name='jar_dependency_management',
  sources=['test_jar_dependency_management.py'],
  dependencies=[
    'src/python/pants/backend/jvm/subsystems:jar_dependency_management',
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='jar_dependency_management_integration',
  sources=['test_jar_dependency_management_integration.py'],
  dependencies=[
    'src/python/pants/fs',
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:depman_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:depman_directory',
    'testprojects/3rdparty:managed_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout=800,
)

python_tests(
  name='jvm_platform',
  sources=['test_jvm_platform.py'],
  dependencies=[
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)
