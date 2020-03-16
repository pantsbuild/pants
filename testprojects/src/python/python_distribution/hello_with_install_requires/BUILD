# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_dist(
  sources=[
    'hello_package/hello.py',
    'hello_package/__init__.py',
    'setup.py'
  ]
)

python_binary(
  name='main_with_no_conflict',
  sources=['main.py'],
  dependencies=[
    ':hello_with_install_requires',
  ],
  platforms=['current']
)
