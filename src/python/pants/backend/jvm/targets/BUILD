
target(
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
    'benchmark.py',
    'credentials.py',
    'exclude.py',
    'exportable_jvm_library.py',
    'import_jars_mixin.py',
    'jar_dependency.py',
    'jar_library.py',
    'jarable.py',
    'junit_tests.py',
    'jvm_app.py',
    'jvm_binary.py',
    'jvm_prep_command.py',
    'jvm_target.py',
    'managed_jar_dependencies.py',
    'tools_jar.py',
    'unpacked_jars.py',
  ],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:six',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/subsystems:java',
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:validation',
    'src/python/pants/build_graph',
    'src/python/pants/fs',
    'src/python/pants/source',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
    'src/python/pants/util:netrc',
    'src/python/pants/util:objects',
  ],
)

python_library(
  name = 'java',
  sources = [
    'annotation_processor.py',
    'java_agent.py',
    'java_library.py',
    'javac_plugin.py',
  ],
  dependencies = [
    '3rdparty/python:six',
    ':jvm',
    'src/python/pants/backend/jvm/subsystems:java',
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
  ],
)

python_library(
  name = 'scala',
  sources = [
    'scala_library.py',
    'scalac_plugin.py',
    'scala_jar_dependency.py',
  ],
  dependencies = [
    ':jvm',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:validation',
    'src/python/pants/build_graph',
    'src/python/pants/util:memo',
  ],
)
