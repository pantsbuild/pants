# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_requirement_library(
  name = 'pex',
  requirements = [
    python_requirement('pex>=2.1.9'),
  ],
)

python_requirement_library(
  name = 'pycountry',
  requirements = [
    python_requirement('pycountry==19.8.18'),
  ],
)

python_library(
  name='hello-lib',
  sources = ['hello_lib.py'],
  tags = {'partially_type_checked'},
)

python_awslambda(
  name='hello-lambda',
  sources = ['hello_handler.py'],
  dependencies=[
    ':pex',
    ':pycountry',
    ':hello-lib',
  ],
  handler='pants.backend.awslambda.python.examples.hello_handler:handler',
  runtime='python3.7'
)
