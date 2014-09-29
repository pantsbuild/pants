
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
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.lang',
    '3rdparty/python:pex',
    '3rdparty/python:setuptools',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:target',
  ],
)
