# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'git_hooks',
  sources = ['test_*.py', '!*integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:git_util',
    'build-support/bin:bash_scripts',
    'build-support/bin:python_scripts',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'git_hooks_integration',
  sources = ['test_*_integration.py'],
  dependencies = [
    '//:gitignore',
    '//:pants_pex',
    'src/python/pants/testutil:git_util',
    'src/python/pants/testutil:int-test',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'build-support:common-script',
    'build-support/bin:bash_scripts',
    'build-support/bin:python_scripts',
    'testprojects/src/python:python_targets_directory',
    'testprojects/src/python:sources_directory',
    'testprojects/tests/scala/org/pantsbuild/testproject:cp-directories_directory',
  ],
  tags = {"partially_type_checked"},
)
