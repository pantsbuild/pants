
python_library(
  name = 'python',
  sources = [
    'python_binary.py',
    'python_library.py',
    'python_requirement_library.py',
    'python_root.py',
    'python_target.py',
    'python_tests.py',
  ],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('3rdparty/python/twitter/commons:twitter.common.quantity'),
    pants('3rdparty/python:setuptools'),
    pants('src/python/pants/base:build_manual'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/python:python_artifact'),
  ],
)