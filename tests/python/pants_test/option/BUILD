# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'option',
  dependencies = [
    ':testing'
  ],
)

python_library(
  name = 'common',
  sources = [
    'fake_config.py',
  ],
)

python_tests(
  name = 'testing',
  sources = [
    'test_arg_splitter.py',
    'test_custom_types.py',
    'test_help_formatter.py',
    'test_help_info_extracter.py',
    'test_option_value_container.py',
    'test_optionable.py',
    'test_options.py',
    'test_options_bootstrapper.py',
    'test_options_fingerprinter.py',
  ],
  dependencies = [
    ':common',
    '3rdparty/python:pytest',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='help_integration',
  sources = [
    'test_help_integration.py',
  ],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
)
