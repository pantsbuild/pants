target(
  name='targets',
  dependencies=[
    ':go_binary',
    ':go_library',
    ':go_local_source',
    ':go_remote_library',
    ':go_thrift_library',
  ]
)

python_library(
  name='go_binary',
  sources=['go_binary.py'],
  dependencies=[
    ':go_local_source',
  ],
)

python_library(
  name='go_library',
  sources=['go_library.py'],
  dependencies=[
    ':go_local_source',
  ],
)

python_library(
  name='go_local_source',
  sources=['go_local_source.py'],
  dependencies=[
    ':go_target',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:parse_context',
    'src/python/pants/base:payload',
    'src/python/pants/source',
  ],
)

python_library(
  name='go_remote_library',
  sources=['go_remote_library.py'],
  dependencies=[
    ':go_target',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
  ],
)

python_library(
  name='go_target',
  sources=['go_target.py'],
  dependencies=[
    'src/python/pants/build_graph'
  ]
)

python_library(
  name='go_thrift_library',
  sources=['go_thrift_library.py'],
  dependencies=[
    ':go_local_source',
    'src/python/pants/base:parse_context',
    'src/python/pants/base:payload',
    'src/python/pants/build_graph',
  ]
)
