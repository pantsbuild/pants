target(
  name='targets',
  dependencies=[
    ':go_binary',
    ':go_library',
    ':go_local_source',
    ':go_remote_library',
  ]
)

python_library(
  name='go_binary',
  sources=['go_binary.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/targets:go_local_source',
  ],
)

python_library(
  name='go_library',
  sources=['go_library.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/targets:go_local_source',
  ],
)

python_library(
  name='go_local_source',
  sources=['go_local_source.py'],
  dependencies=[
    'src/python/pants/base:payload',
    'src/python/pants/base:target',
  ],
)

python_library(
  name='go_remote_library',
  sources=['go_remote_library.py'],
  dependencies=[
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:target',
  ],
)
