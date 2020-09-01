# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_distribution(
  name='testutil_wheel',
  dependencies=[
    ':testutil',
    ':int-test-for-export',
  ],
  provides=setup_py(
    name='pantsbuild.pants.testutil',
    description='Test support for writing Pants plugins.',
    namespace_packages=['pants.testutil'],
    classifiers=[
      'Topic :: Software Development :: Testing',
    ]
  )
)

python_library(
  sources=[
    "*.py",
    "!rule_runner.py",
    "!test_base.py",
    "!pants_integration_test.py",
    "!pants_run_integration_test.py",
    "!_test.py",
  ],
)

python_library(
  name="rule_runner",
  sources=["rule_runner.py", "test_base.py"],
  dependencies=["//:build_root"],
)

python_library(
  name = 'int-test-for-export',
  sources = ['pants_integration_test.py', 'pants_run_integration_test.py'],
  dependencies = [
    '//:build_root',
    'src/python/pants:entry_point'
  ],
)

target(
  name = 'int-test',
  dependencies=[
    ':int-test-for-export',
    # NB: 'pants_run_integration_test.py' runs ./pants in a subprocess using the PYTHONPATH
    # of the testrunner. We include the pants binary itself to fully populate the path.
    'src/python/pants/bin:pants_local_binary',
  ],
)

python_tests(
  name='tests',
  sources=['*_test.py', '!pants_integration_test.py', '!pants_run_integration_test.py']
)
