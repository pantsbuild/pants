# XXX this is not an advisable target going forward as we split out into build plugins
python_library(
  name = 'all',
  dependencies = [
    pants(':common'),
    pants(':jvm'),
    pants(':java'),
    pants(':python'),
    pants(':scala'),
  ],
)

python_library(
  name = 'common',
  sources = [
    'anonymous.py',
    'doc.py',
    'external_dependency.py',
    'pants_target.py',
    'repository.py',
    'resources.py',  # XXX dependency on InternalTarget which is an abstraction leak
    'sources.py',
    'util.py',
    'with_dependencies.py',
    'with_sources.py',
  ],
  dependencies = [
    # pants(':jvm'), XXX internal.py is in :jvm, so common won't work without it.
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/pants/base:address'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:build_manual'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
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
    'internal.py',  # XXX fixme
    'jar_dependency.py',
    'jar_library.py',
    'jarable.py',
    'jvm_binary.py',
    'jvm_target.py',
  ],
  dependencies = [
    pants(':common'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/pants/base:build_manual'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
  ],
)

python_library(
  name = 'java',
  sources = [
    'annotation_processor.py',
    'java_agent.py',
    'java_antlr_library.py',
    'java_library.py',
    'java_protobuf_library.py',
    'java_tests.py',
    'java_thrift_library.py',
  ],
  dependencies = [
    pants(':common'),
    pants(':jvm'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/pants/base:build_manual'),
    pants('src/python/twitter/pants/base:target'),
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
    pants(':common'),
    pants(':jvm'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/pants/base:build_manual'),
    pants('src/python/twitter/pants/base:target'),
  ],
)

python_library(
  name = 'python',
  sources = [
    'python_antlr_library.py',
    'python_artifact.py',
    'python_binary.py',
    'python_egg.py',
    'python_library.py',
    'python_requirement.py',
    'python_target.py',
    'python_tests.py',
    'python_thrift_library.py',
  ],
  dependencies = [
    pants('3rdparty/python:setuptools'),
    pants(':common'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/common/quantity'),
    pants('src/python/twitter/pants/base:build_manual'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
  ],
)
