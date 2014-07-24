
python_library(
  name = 'java',
  sources = [
    'java_antlr_library.py',
    'java_protobuf_library.py',
    'java_thrift_library.py',
    'java_ragel_library.py',
    'jaxb_library.py',
  ],
  dependencies = [
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'python',
  sources = [
    'python_antlr_library.py',
    'python_thrift_library.py',
  ],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/backend/python/targets:python'),
  ],
)
