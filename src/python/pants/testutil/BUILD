# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='testutil_wheel',
  sources=[],
  dependencies=[
    ':testutil',
    ':int-test-for-export',
    'src/python/pants/testutil/engine',
    'src/python/pants/testutil/option',
  ],
  provides=pants_setup_py(
    name='pantsbuild.pants.testutil',
    description='Test support for writing Pants plugins.',
    namespace_packages=['pants.testutil'],
    additional_classifiers=[
      'Topic :: Software Development :: Testing',
    ]
  )
)

python_library(
  sources=['*.py', '!pants_run_integration_test.py', '!_test.py'],
)

python_library(
  name = 'int-test-for-export',
  sources = ['pants_run_integration_test.py'],
  dependencies = [
    '//:build_root',
    'src/python/pants:entry_point'
  ],
)

target(
  name = 'int-test',
  dependencies=[
    ':int-test-for-export',
    # NB: 'pants_run_integration_test.py' runs ./pants in a subprocess, so test results will depend
    # on the pants binary and all of its transitive dependencies. Adding the dependencies below is
    # our best proxy for ensuring that any test target depending on this target will be invalidated
    # on changes to those undeclared dependencies.
    'src/python/pants/bin:pants_local_binary',
    'src/rust/engine',
  ],
)

python_tests(
  name='tests',
  sources=['*_test.py', '!pants_run_integration_test.py']
)
