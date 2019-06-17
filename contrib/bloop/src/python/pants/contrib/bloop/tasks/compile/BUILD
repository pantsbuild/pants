python_library(
  dependencies=[
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/java/jar',
    'contrib/bloop/3rdparty/src/bsp:proto-py',
    '3rdparty/python:protobuf',
    # TODO: make this work in pants source!! fails on plugin loading if not in the pants venv!!
    # 'contrib/bloop/3rdparty/py:protobuf',
  ],
)
