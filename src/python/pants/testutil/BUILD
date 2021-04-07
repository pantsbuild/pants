# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_distribution(
  name='testutil_wheel',
  dependencies=[
    ':testutil',
    ':pants_integration_test',
    ':rule_runner',
  ],
  setup_py_commands=["bdist_wheel", "--python-tag", "py37.py38.py39", "sdist"],
  provides=setup_py(
    name='pantsbuild.pants.testutil',
    description='Test support for writing Pants plugins.',
    classifiers=[
      'Topic :: Software Development :: Testing',
    ]
  ),
)

python_library(
  sources=[
    "*.py",
    "!rule_runner.py",
    "!test_base.py",
    "!pants_integration_test.py",
    "!_test.py",
  ],
)

python_library(
  name="rule_runner",
  sources=["rule_runner.py", "test_base.py"],
  dependencies=["//:build_root"],
)

python_library(
  name = 'pants_integration_test',
  sources = ['pants_integration_test.py'],
  dependencies = [
    '//:build_root',
    'src/python/pants:entry_point'
  ],
)

python_tests(
  name='tests',
  sources=['*_test.py', '!pants_integration_test.py']
)
