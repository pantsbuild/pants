
python_library(
  name = 'java',
  sources = [
    'java_antlr_library.py',
    'java_protobuf_library.py',
    'java_thrift_library.py',
    'java_ragel_library.py',
    'java_wire_library.py',
    'jaxb_library.py',
  ],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.lang',
    '3rdparty/python:six',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:config',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:target',
  ],
)

python_library(
  name = 'python',
  sources = [
    'python_antlr_library.py',
    'python_thrift_library.py',
  ],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/python/targets:python',
  ],
)
