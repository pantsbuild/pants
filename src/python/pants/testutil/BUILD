# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_distribution(
  name='testutil_wheel',
  dependencies=[
    ':testutil',
    ':pants_integration_test',
    ':rule_runner',
    ':py_typed',
  ],
  wheel_config_settings={"--global-option": ["--python-tag", "py37.py38.py39"]},
  provides=setup_py(
    name='pantsbuild.pants.testutil',
    description='Test support for writing Pants plugins.',
    classifiers=[
      'Topic :: Software Development :: Testing',
    ]
  ),
)

python_sources(
  sources=[
    "*.py",
    "!rule_runner.py",
    "!test_base.py",
    "!pants_integration_test.py",
    "!_test.py",
  ],
)

python_sources(
  name="rule_runner",
  sources=["rule_runner.py", "test_base.py"],
  dependencies=["//BUILD_ROOT:files"],
)

python_sources(
  name = 'pants_integration_test',
  sources = ['pants_integration_test.py'],
  dependencies = [
    "//BUILD_ROOT:files",
    'src/python/pants:entry_point'
  ],
)

python_tests(
  name='tests',
  sources=['*_test.py', '!pants_integration_test.py']
)

resources(
  name="py_typed",
  sources=["py.typed"],
)
