target(
    dependencies=[
    ':cargo_base_binary',
    ':cargo_base_custom_build',
    ':cargo_base_library',
    ':cargo_base_proc_macro',
    ':cargo_base_target',
    ':cargo_base_test',
    ':cargo_binary',
    ':cargo_library',
    ':cargo_synthetic_binary',
    ':cargo_synthetic_custom_build',
    ':cargo_synthetic_library',
    ':cargo_synthetic_proc_macro',
    ':cargo_target',
    ':cargo_test',
    ':cargo_workspace',
  ]
)


python_library(
    name='cargo_base_binary',
    sources=['cargo_base_binary.py'],
    dependencies=[
        ':cargo_base_target',
        '3rdparty/python:future',
   ]
)

python_library(
   name='cargo_base_custom_build',
   sources=['cargo_base_custom_build.py'],
   dependencies=[
     ':cargo_base_target',
     '3rdparty/python:future',
   ]
)

python_library(
   name='cargo_base_library',
   sources=['cargo_base_library.py'],
   dependencies=[
     ':cargo_base_target',
     '3rdparty/python:future',
   ]
)

python_library(
   name='cargo_base_proc_macro',
   sources=['cargo_base_proc_macro.py'],
   dependencies=[
     ':cargo_base_target',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_base_target',
   sources=['cargo_base_target.py'],
   dependencies=[
     'src/python/pants/build_graph',
     'src/python/pants/base:payload',
     'src/python/pants/base:payload_field',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_base_test',
   sources=['cargo_base_test.py'],
   dependencies=[
     ':cargo_base_target',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_binary',
   sources=['cargo_binary.py'],
   dependencies=[
     ':cargo_base_binary',
     'src/python/pants/base:payload',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_library',
   sources=['cargo_library.py'],
   dependencies=[
     ':cargo_base_library',
     'src/python/pants/base:payload',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_synthetic_binary',
   sources=['cargo_synthetic_binary.py'],
   dependencies=[
     ':cargo_base_binary',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_synthetic_custom_build',
   sources=['cargo_synthetic_custom_build.py'],
   dependencies=[
     ':cargo_base_custom_build',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_synthetic_library',
    sources=['cargo_synthetic_library.py'],
    dependencies=[
        ':cargo_base_library',
        '3rdparty/python:future',
    ]
)

python_library(
    name='cargo_synthetic_proc_macro',
   sources=['cargo_synthetic_proc_macro.py'],
   dependencies=[
     ':cargo_base_proc_macro',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_target',
   sources=['cargo_target.py'],
   dependencies=[
     'src/python/pants/build_graph',
     'src/python/pants/base:payload',
     'src/python/pants/base:payload_field',
     'src/python/pants/base:build_environment',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_test',
   sources=['cargo_test.py'],
   dependencies=[
     ':cargo_base_test',
     'src/python/pants/base:payload',
     '3rdparty/python:future',
   ]
)

python_library(
    name='cargo_workspace',
   sources=['cargo_workspace.py'],
   dependencies=[
     ':cargo_target',
     'src/python/pants/base:payload',
     'src/python/pants/base:payload_field',
     'src/python/pants/base:build_environment',
     '3rdparty/python:future',
   ]
)



