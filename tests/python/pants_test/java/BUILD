# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'executor',
  sources = ['test_executor.py'],
  dependencies = [
    'src/python/pants/java/distribution:distribution',
    'src/python/pants/java:executor',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'nailgun_client',
  sources = ['test_nailgun_client.py'],
  coverage = ['pants.java.nailgun_client'],
  dependencies = [
    'src/python/pants/java:nailgun_client',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'nailgun_executor',
  sources = ['test_nailgun_executor.py'],
  coverage = ['pants.java.nailgun_executor'],
  dependencies = [
    '3rdparty/python:psutil',
    'src/python/pants/java:nailgun_executor',
    'src/python/pants/testutil:test_base'
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'nailgun_io',
  sources = ['test_nailgun_io.py'],
  coverage = ['pants.java.nailgun_io'],
  dependencies = [
    'src/python/pants/java:nailgun_io',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'nailgun_protocol',
  sources = ['test_nailgun_protocol.py'],
  coverage = ['pants.java.nailgun_protocol'],
  dependencies = [
    'src/python/pants/java:nailgun_protocol',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'util',
  sources = ['test_util.py'],
  dependencies = [
    'src/python/pants/java:util',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'nailgun_integration',
  sources = ['test_nailgun_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 800,
)

python_tests(
  name = 'test_runjava',
  sources = ['test_runjava_synthetic_classpath.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/java:util',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
  ],
  tags = {"partially_type_checked"},
)
