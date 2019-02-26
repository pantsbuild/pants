target(
  dependencies=[
    ':cargo_project_binary',
    ':cargo_project_library',
    ':cargo_project_test',
    ':cargo_synthetic_base',
    ':cargo_synthetic_binary',
    ':cargo_synthetic_library',
    ':cargo_synthetic_custom_build',
    ':cargo_synthetic_proc_macro',
  ]
)

python_library(
  name='cargo_project_binary',
  sources=['cargo_project_binary.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/base:payload',
    ':cargo_synthetic_binary',
  ]
)

python_library(
  name='cargo_project_library',
  sources=['cargo_project_library.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/base:payload',
    ':cargo_synthetic_library',
  ]
)

python_library(
  name='cargo_project_test',
  sources=['cargo_project_test.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/base:payload',
    ':cargo_synthetic_base',
  ]
)

python_library(
  name='cargo_synthetic_base',
  sources=['cargo_synthetic_base.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/build_graph',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
  ]
)

python_library(
  name='cargo_synthetic_binary',
  sources=['cargo_synthetic_binary.py'],
  dependencies=[
    '3rdparty/python:future',
    ':cargo_synthetic_base',
  ]
)

python_library(
  name='cargo_synthetic_library',
  sources=['cargo_synthetic_library.py'],
  dependencies=[
    '3rdparty/python:future',
    ':cargo_synthetic_base',
  ]
)

python_library(
  name='cargo_synthetic_custom_build',
  sources=['cargo_synthetic_custom_build.py'],
  dependencies=[
    '3rdparty/python:future',
    ':cargo_synthetic_base',
  ]
)

python_library(
  name='cargo_synthetic_proc_macro',
  sources=['cargo_synthetic_proc_macro.py'],
  dependencies=[
    '3rdparty/python:future',
    ':cargo_synthetic_base',
  ]
)




