# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='shader',
  sources=['test_shader.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
)

python_tests(
  name='custom_scala',
  sources=['test_custom_scala.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:scalastyle',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
)

python_tests(
  name='incomplete_custom_scala',
  sources=['test_incomplete_custom_scala.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
  timeout=180,
)

python_tests(
  name='shader_integration',
  sources=['test_shader_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/fs',
    'src/python/pants/java/distribution',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name='jar_dependency_management',
  sources=['test_jar_dependency_management.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:jar_dependency_management',
    'src/python/pants/backend/jvm:jar_dependency_utils',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
)

python_tests(
  name='jar_dependency_management_integration',
  sources=['test_jar_dependency_management_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
  timeout=180,
)
