target(
  dependencies=[
    ':args_rules',
    ':env_rules',
    ':links_rule',
    ':outputs_rule',
    ':program_rule',
  ]
)

python_library(
  name='args_rules',
  sources=['args_rules.py'],
  dependencies=[
    '3rdparty/python:future',
    'contrib/rust/src/python/pants/contrib/rust/utils/basic_invocation:args_rules',
  ]
)

python_library(
  name='env_rules',
  sources=['env_rules.py'],
  dependencies=[
    '3rdparty/python:future',
    'contrib/rust/src/python/pants/contrib/rust/targets/synthetic:cargo_synthetic_custom_build',
  ]
)

python_library(
  name='links_rule',
  sources=['links_rule.py'],
  dependencies=[
    '3rdparty/python:future',
  ]
)

python_library(
  name='outputs_rule',
  sources=['outputs_rule.py'],
  dependencies=[
    '3rdparty/python:future',
  ]
)

python_library(
  name='program_rule',
  sources=['program_rule.py'],
  dependencies=[
    '3rdparty/python:future',
  ]
)