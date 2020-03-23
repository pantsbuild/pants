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
  source='settings.py',
  dependencies=[
    ':django-stubs',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='valid',
  source='valid.py',
  dependencies=[
    ':django',
    ':settings',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='invalid',
  source='invalid.py',
  dependencies=[
    ':django',
    ':settings',
  ],
)
