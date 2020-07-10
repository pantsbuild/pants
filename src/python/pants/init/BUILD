# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    ':plugins',
  ],
)

target(
  name='plugins',
  dependencies=[
    'src/python/pants/backend/awslambda/python',
    'src/python/pants/backend/codegen/protobuf/python',
    'src/python/pants/backend/pants_info',
    'src/python/pants/backend/project_info',
    'src/python/pants/backend/python',
    'src/python/pants/backend/python/lint/bandit',
    'src/python/pants/backend/python/lint/black',
    'src/python/pants/backend/python/lint/docformatter',
    'src/python/pants/backend/python/lint/flake8',
    'src/python/pants/backend/python/lint/isort',
    'src/python/pants/backend/python/lint/pylint',
    'src/python/pants/backend/python/typecheck/mypy',
    'src/python/pants/backend/native',
    'src/python/pants/core',
  ],
)
