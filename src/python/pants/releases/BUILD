# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name = 'reversion',
  source = 'reversion.py',
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/util:contextutil',
  ],
)

python_binary(
  name = 'packages',
  source = 'packages.py',
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:configparser',
    '3rdparty/python:beautifulsoup4',
    'src/python/pants/util:process_handler',
  ],
  tags={'platform_specific_behavior'},
)
