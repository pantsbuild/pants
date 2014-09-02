# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='base',
  dependencies=[
    'tests/python/pants_test:base_test',
  ],
)

target(
  name='targets',
  dependencies=[
    ':artifact',
    ':exclusive',
    ':jar_library',
    ':java_agent',
    ':java_tests',
    ':java_thrift_library',
    ':jvm_app',
    ':python_binary',
    ':python_target',
    ':scala_library',
    ':sort_targets',
    ':wiki_page'
  ]
)

target(
  name='integration',
  dependencies=[
    ':scala_library_integration',
  ],
)

python_tests(
  name='artifact',
  sources=['test_artifact.py'],
  dependencies=[
    ':base',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:jvm',
  ],
  coverage=[
    'pants.backend.jvm.targets.artifact',
  ]
)

python_tests(
  name='jvm_app',
  sources=['test_jvm_app.py'],
  dependencies=[
    ':base',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/base:exceptions',
  ],
  coverage=[
    'pants.backend.jvm.targets.jvm_binary',
  ]
)

# TODO(John Sirois): re-locate, this really tests the verbs use of the nouns.
python_tests(
  name='exclusive',
  sources=['test_exclusive.py'],
  dependencies=[
    'src/python/pants/base:config',
    'src/python/pants/backend/core/tasks:check_exclusives',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ],
  coverage=[
    'pants.backend.core.tasks.check_exclusives',
  ]
)

# TODO(John Sirois): re-locate, this tests the BuildGraph.
python_tests(
  name='sort_targets',
  sources=['test_sort_targets.py'],
  dependencies=[
    ':base',
    'src/python/pants/base:target',
    'src/python/pants/base:build_graph',
    'src/python/pants/base:payload',
    'src/python/pants/backend/core/targets:common',
  ],
  coverage=[
    'pants.base.build_graph',
  ]
)

python_tests(
  name='jar_library',
  sources=['test_jar_library.py'],
  dependencies=[
    ':base',
    'src/python/pants/base:target',
    'src/python/pants/backend/jvm/targets:jvm',
  ],
  coverage=[
    'pants.backend.jvm.targets.jar_library',
  ]
)

python_tests(
  name='java_thrift_library',
  sources=['test_java_thrift_library.py'],
  dependencies=[
    ':base',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_file_aliases',
    'tests/python/pants_test/base:context_utils',
  ],
  coverage=[
    'pants.backend.codegen.targets.java_thrift_library',
  ]
)

python_tests(
  name='java_agent',
  sources=['test_java_agent.py'],
  dependencies=[
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test:base_test',
  ],
  coverage=[
    'pants.backend.jvm.targets.java_agent',
  ]
)

python_tests(
  name='java_tests',
  sources=['test_java_tests.py'],
  dependencies=[
    ':base',
    'src/python/pants/backend/core',
    'src/python/pants/backend/jvm/targets:java',
    'tests/python/pants_test/base:context_utils',
  ],
  coverage=[
    'pants.backend.jvm.targets.java_tests',
  ]
)

python_tests(
  name='python_binary',
  sources=['test_python_binary.py'],
  dependencies=[
    ':base',
    'src/python/pants/base:target',
    'src/python/pants/backend/python/targets:python',
  ],
  coverage=[
    'pants.backend.python.targets.python_binary',
  ]
)

python_tests(
  name='scala_library',
  sources=['test_scala_library.py'],
  dependencies=[
    ':base',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/base:build_file_aliases',
  ],
  coverage=[
    'pants.backend.jvm.targets.scala_library',
  ]
)

# TODO(John Sirois): re-locate, this really tests the verbs use of the nouns.
python_tests(
  name='scala_library_integration',
  sources=['test_scala_library_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  coverage=[
    'pants.backend.jvm.tasks.jvm_compile.scala.scala_compile',
  ]
)

python_tests(
  name='python_target',
  sources=['test_python_target.py'],
  dependencies=[
    ':base',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:source_root',
    'src/python/pants/base:target',
  ],
  coverage=[
    'pants.backend.python.targets.python_target',
  ]
)

python_tests(
  name='wiki_page',
  sources=['test_wiki_page.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.confluence',
    'src/python/pants/backend/core/targets:common',
    'tests/python/pants_test:base_test',
  ],
  coverage=[
    'pants.backend.core.targets.doc',
  ]
)
