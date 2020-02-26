
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
    'exportable_jvm_library.py',
    'import_jars_mixin.py',
    'jar_library.py',
    'jarable.py',
    'junit_tests.py',
    'jvm_app.py',
    'jvm_binary.py',
    'jvm_prep_command.py',
    'jvm_target.py',
    'managed_jar_dependencies.py',
    'runtime_platform_mixin.py',
    'tools_jar.py',
    'unpacked_jars.py',
  ],
  dependencies = [
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
    'src/python/pants/util:netrc',
    'src/python/pants/util:objects',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
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
    ':jvm',
    'src/python/pants/backend/jvm/subsystems:java',
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'scala',
  sources = [
    'scala_library.py',
    'scalac_plugin.py',
    'scala_jar_dependency.py',
    'scala_exclude.py',
  ],
  dependencies = [
    ':jvm',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:scoverage_platform',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:validation',
    'src/python/pants/build_graph',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)
