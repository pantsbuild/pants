# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=['*.py', '!report.py'],
  dependencies=[
    ':reporting_resources',
  ],
)

resources(
  name='reporting_resources',
  sources=['assets/**/*', 'templates/**/*.mustache'],
)

python_library(
  name='report',
  sources=['report.py'],
)
