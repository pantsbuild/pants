# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='tasks',
  dependencies=[
    ':scm_publish',
  ],
)

python_tests(
  name='scm_publish',
  sources=['test_scm_publish.py'],
  coverage=['pants.backend.core.tasks.scm_publish'],
  dependencies=[
    '3rdparty/python:mock',
    'src/python/pants/backend/core/tasks:scm_publish',
  ]
)
