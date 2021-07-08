# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(dependencies=[":plugins"])

target(
  name='plugins',
  dependencies=[
    'src/python/pants/backend/awslambda/python',
    'src/python/pants/backend/codegen/protobuf/python',
    'src/python/pants/backend/experimental/go',
    'src/python/pants/backend/experimental/go/lint/gofmt',
    'src/python/pants/backend/experimental/terraform',
    'src/python/pants/backend/experimental/terraform/lint/tffmt',
    'src/python/pants/backend/experimental/terraform/lint/validate',
    'src/python/pants/backend/project_info',
    'src/python/pants/backend/python',
    'src/python/pants/backend/python/lint/bandit',
    'src/python/pants/backend/python/lint/black',
    'src/python/pants/backend/python/lint/docformatter',
    'src/python/pants/backend/python/lint/flake8',
    'src/python/pants/backend/python/lint/isort',
    'src/python/pants/backend/python/lint/pylint',
    'src/python/pants/backend/python/mixed_interpreter_constraints',
    'src/python/pants/backend/python/typecheck/mypy',
    'src/python/pants/backend/shell',
    'src/python/pants/backend/shell/lint/shellcheck',
    'src/python/pants/backend/shell/lint/shfmt',
    'src/python/pants/core',
  ],
)

python_tests(name="tests", timeout=200)
