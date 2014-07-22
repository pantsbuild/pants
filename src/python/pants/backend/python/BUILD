# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/backend/python/commands:pants_old'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/backend/python/tasks:python'),
    pants(':all_utils'),
  ]
)

python_library(
  name = 'all_utils',
  dependencies = [
    pants(':python_setup'),
    pants(':antlr_builder'),
    pants(':binary_builder'),
    pants(':code_generator'),
    pants(':interpreter_cache'),
    pants(':python_artifact'),
    pants(':python_builder'),
    pants(':python_chroot'),
    pants(':python_requirement'),
    pants(':python_requirements'),
    pants(':resolver'),
    pants(':sdist_builder'),
    pants(':test_builder'),
    pants(':thrift_builder'),
  ]
)

page(
  name = 'readme',
  source = 'README.md',
  dependencies = [
    pants('src/python/pants:readme'),
  ]
)

python_library(
  name = 'python_setup',
  sources = ['python_setup.py'],
  dependencies = [
    pants('src/python/pants/base:config'),
  ]
)

python_library(
  name = 'antlr_builder',
  sources = ['antlr_builder.py'],
  dependencies = [
    pants(':code_generator'),
    pants('3rdparty/python:antlr-3.1.3'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_library(
  name = 'binary_builder',
  sources = ['binary_builder.py'],
  dependencies = [
    pants(':code_generator'),
    pants(':python_chroot'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/backend/python/targets:python'),
  ]
)

python_library(
  name = 'code_generator',
  sources = ['code_generator.py'],
  dependencies = [
    pants(':sdist_builder'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
  ]
)


python_library(
  name = 'interpreter_cache',
  sources = ['interpreter_cache.py'],
  dependencies = [
    pants('3rdparty/python:setuptools'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants(':python_setup'),
    pants(':resolver'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_library(
  name = 'python_artifact',
  sources = ['python_artifact.py'],
  dependencies = [],
)

python_library(
  name = 'python_builder',
  sources = ['python_builder.py'],
  dependencies = [
    pants(':binary_builder'),
    pants(':python_chroot'),
    pants(':test_builder'),
    pants('src/python/pants/backend/python/targets:python'),
  ],
)

python_library(
  name = 'python_chroot',
  sources = ['python_chroot.py'],
  dependencies = [
    pants(':antlr_builder'),
    pants(':python_setup'),
    pants(':resolver'),
    pants(':thrift_builder'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.decorators'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('3rdparty/python/twitter/commons:twitter.common.quantity'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:build_invalidator'),
    pants('src/python/pants/util:dirutil')
  ],
)

python_library(
  name = 'python_requirement',
  sources = ['python_requirement.py'],
)

python_library(
  name = 'python_requirements',
  sources = ['python_requirements.py'],
)

python_library(
  name = 'resolver',
  sources = ['resolver.py'],
  dependencies = [
    pants(':python_setup'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/backend/python/targets:python'),
  ],
)

python_library(
  name = 'sdist_builder',
  sources = ['sdist_builder.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
  ]
)

python_library(
  name = 'test_builder',
  sources = ['test_builder.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('3rdparty/python:pytest'),
    pants('3rdparty/python:pytest-cov'),
    pants(':python_chroot'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'thrift_builder',
  sources = ['thrift_builder.py'],
  dependencies = [
    pants(':code_generator'),
    pants('src/python/pants/backend/codegen/targets:python'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants:thrift_util'),
    pants('src/python/pants/util:dirutil'),
  ]
)
