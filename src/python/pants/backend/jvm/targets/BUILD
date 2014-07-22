
python_library(
  name = 'all',
  dependencies = [
    ':jvm',
    ':java',
    ':scala',
  ],
)

python_library(
  name = 'jvm',
  sources = [
    'artifact.py',
    'benchmark.py',
    'credentials.py',
    'exclude.py',
    'exportable_jvm_library.py',
    'jar_dependency.py',
    'jar_library.py',
    'jarable.py',
    'jvm_binary.py',
    'jvm_target.py',
    'repository.py',
  ],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_manual'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:payload'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'java',
  sources = [
    'annotation_processor.py',
    'java_agent.py',
    'java_library.py',
    'java_tests.py',
  ],
  dependencies = [
    pants(':jvm'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'scala',
  sources = [
    'scala_library.py',
    'scala_tests.py',
    'scalac_plugin.py',
  ],
  dependencies = [
    pants(':jvm'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/backend/jvm/scala:target_platform'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:target'),
  ],
)
