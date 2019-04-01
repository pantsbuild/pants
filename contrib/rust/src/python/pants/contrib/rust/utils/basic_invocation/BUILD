target(
  dependencies=[
    ':args_rules',
    ':c_flag_rules',
    ':l_flag_rules',
    ':env_rules',
    ':links_rule',
    ':outputs_rule',
  ]
)

python_library(
  name='args_rules',
  sources=['args_rules.py'],
  dependencies=[
    '3rdparty/python:future',
    ':c_flag_rules',
    ':l_flag_rules',
  ]
)

python_library(
  name='c_flag_rules',
  sources=['c_flag_rules.py'],
  dependencies=[
    '3rdparty/python:future',
  ]
)

python_library(
  name='l_flag_rules',
  sources=['l_flag_rules.py'],
  dependencies=[
    '3rdparty/python:future',
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