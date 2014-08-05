
python_library(
  name = 'python',
  sources = [
    'python_binary.py',
    'python_library.py',
    'python_requirement_library.py',
    'python_target.py',
    'python_tests.py',
  ],
  dependencies = [
    pants('3rdparty/python:pex'),
    pants('3rdparty/python:setuptools'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/python:python_artifact'),
    pants('src/python/pants/base:target'),
  ],
)