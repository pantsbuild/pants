target(
  dependencies=[
    ':cargo_base',
    ':cargo_binary',
    ':cargo_library',
    ':cargo_workspace',
  ]
)

python_library(
  name='cargo_base',
  sources=['cargo_base.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/build_graph',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:build_environment',
  ]
)

python_library(
  name='cargo_binary',
  sources=['cargo_binary.py'],
  dependencies=[
    '3rdparty/python:future',
    ':cargo_base',
  ]
)

python_library(
    name='cargo_library',
   sources=['cargo_library.py'],
   dependencies=[
     '3rdparty/python:future',
     ':cargo_base',
   ]
)

python_library(
  name='cargo_workspace',
  sources=['cargo_workspace.py'],
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python:toml',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:build_environment',
    ':cargo_base',
   ]
)



