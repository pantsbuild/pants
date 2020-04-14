# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_requirement_library(
  name='django',
  requirements=[
    python_requirement('Django==2.2.5'),
  ],
)

python_requirement_library(
  name='django-stubs',
  requirements=[
    python_requirement('django-stubs==1.1.0'),
  ],
)

python_library(
  name='settings',
  sources=['settings.py'],
  dependencies=[
    ':django-stubs',
  ],
)

python_library(
  name='valid',
  sources=['valid.py'],
  dependencies=[
    ':django',
    ':settings',
  ],
)

python_library(
  name='invalid',
  sources=['invalid.py'],
  dependencies=[
    ':django',
    ':settings',
  ],
)
