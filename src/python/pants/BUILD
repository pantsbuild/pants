# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='pants',
  dependencies=[
    'src/python/pants/bin:pants',
  ],
  description='An alias for the pants binary target.',
)

python_library(
  name='pants-packaged',
  provides=pants_setup_py(
    name='pantsbuild.pants',
    description='A bottom-up build tool.',
    namespace_packages=['pants'],
  ).with_binaries(
    pants='src/python/pants/bin:pants',
  )
)

python_library(
  name='test_infra',
  dependencies=[
    'tests/python/pants_test:base_test',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/jvm:jar_task_test_base',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
    'tests/python/pants_test/engine:engine_test_base',

    # TODO(John Sirois): Remove this once setup-py learns to index providers that are out of scope.
    # see: https://github.com/pantsbuild/pants/issues/1329
    'src/python/pants:pants-packaged',
  ],
  provides=pants_setup_py(
    name='pantsbuild.pants.testinfra',
    description='Test support for writing pants plugins.',
    namespace_packages=['pants_test'],
    additional_classifiers=[
      'Topic :: Software Development :: Testing',
    ]
  )
)

page(name='readme',
  source='README.md',
)

# XXX move into base or thrift
python_library(
  name='binary_util',
  sources=['binary_util.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:six',
    'src/python/pants/base:config',
    'src/python/pants/base:exceptions',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name='thrift_util',
  sources=['thrift_util.py'],
  dependencies=[
    ':binary_util',
  ],
)

python_library(
  name='version',
  sources=['version.py'],
)

page(
  name='changelog',
  source='CHANGELOG.rst'
)
