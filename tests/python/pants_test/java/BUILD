# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'executor',
  sources = ['test_executor.py'],
  dependencies = [
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name = 'nailgun_client',
  sources = ['test_nailgun_client.py'],
  coverage = ['pants.java.nailgun_client'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/java:nailgun_client',
    'src/python/pants/java:nailgun_io',
    'src/python/pants/java:nailgun_protocol',
  ],
)

python_tests(
  name = 'nailgun_executor',
  sources = ['test_nailgun_executor.py'],
  coverage = ['pants.java.nailgun_executor'],
  dependencies = [
    '3rdparty/python:mock',
    '3rdparty/python:psutil',
    'src/python/pants/java:nailgun_executor',
  ],
)

python_tests(
  name = 'nailgun_io',
  sources = ['test_nailgun_io.py'],
  coverage = ['pants.java.nailgun_io'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/java:nailgun_io',
    'src/python/pants/java:nailgun_protocol',
  ],
)

python_tests(
  name = 'nailgun_protocol',
  sources = ['test_nailgun_protocol.py'],
  coverage = ['pants.java.nailgun_protocol'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/java:nailgun_protocol',
  ],
)

python_tests(
  name = 'util',
  sources = ['test_util.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/java/jar:manifest',
    'src/python/pants/java:executor',
    'src/python/pants/java:util',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name = 'nailgun_integration',
  sources = ['test_nailgun_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)
