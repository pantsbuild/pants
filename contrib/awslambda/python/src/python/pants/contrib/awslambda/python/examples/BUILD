# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_requirement_library(
  name = 'pycountry',
  requirements = [
    python_requirement('pycountry==18.5.20'),
  ],
)

python_library(
  name='hello-lib',
  sources = ['hello_lib.py'],
)

python_binary(
  name='hello-bin',
  source='hello_handler.py',
  dependencies=[
    ':pycountry',
    ':hello-lib',
  ]
)

python_awslambda(
  name='hello-lambda',
  binary=':hello-bin',
  handler='pants.contrib.awslambda.python.examples.hello_handler:handler'
)
