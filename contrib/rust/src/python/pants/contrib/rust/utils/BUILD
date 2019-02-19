target(
  dependencies=[
    ':basic_invocation_conversion',
    ':basic_invocation_conversion_rules',
    ':basic_invocation_conversion_utils',
    ':collector',
    ':custom_build_invocation_conversion',
    ':custom_build_invocation_conversion_rules',
    ':custom_build_output_parsing',
  ]
)

python_library(
   name='basic_invocation_conversion',
   sources=['basic_invocation_conversion.py'],
   dependencies=[
     ':basic_invocation_conversion_rules',
     ':basic_invocation_conversion_utils',
     ':collector',
     'contrib/rust/src/python/pants/contrib/rust/tasks:cargo_task',
     'src/python/pants/base:build_environment',
     'src/python/pants/base:exceptions',
     'src/python/pants/base:workunit',
     'src/python/pants/util:dirutil',
     'src/python/pants/util:process_handler',
     '3rdparty/python:future',
   ]
)

python_library(
   name='basic_invocation_conversion_rules',
   sources=['basic_invocation_conversion_rules.py'],
   dependencies=[
     'contrib/rust/src/python/pants/contrib/rust/targets:cargo_synthetic_custom_build',
     '3rdparty/python:future',
   ]
)

python_library(
   name='basic_invocation_conversion_utils',
   sources=['basic_invocation_conversion_utils.py'],
   dependencies=[
     '3rdparty/python:future',
   ]
)

python_library(
   name='collector',
   sources=['collector.py'],
   dependencies=[
     '3rdparty/python:future',
   ]
)

python_library(
   name='custom_build_invocation_conversion',
   sources=['custom_build_invocation_conversion.py'],
   dependencies=[
     ':basic_invocation_conversion_utils',
     ':custom_build_invocation_conversion_rules',
     ':collector',
     'src/python/pants/base:exceptions',
     '3rdparty/python:future',
   ]
)

python_library(
   name='custom_build_invocation_conversion_rules',
   sources=['custom_build_invocation_conversion_rules.py'],
   dependencies=[
     '3rdparty/python:future',
   ]
)

python_library(
   name='custom_build_output_parsing',
   sources=['custom_build_output_parsing.py'],
   dependencies=[
     '3rdparty/python:future',
   ]
)


