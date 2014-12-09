# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/goal:task_registrar',
    ':all_utils',
  ]
)

python_library(
  name = 'all_utils',
  dependencies = [
    ':antlr_builder',
    ':binary_builder',
    ':code_generator',
    ':interpreter_cache',
    ':python_artifact',
    ':python_builder',
    ':python_chroot',
    ':python_requirement',
    ':python_requirements',
    ':python_setup',
    ':resolver',
    ':sdist_builder',
    ':test_builder',
    ':thrift_builder',
  ]
)

page(
  name = 'readme',
  source = 'README.md',
  links = [
    'src/python/pants:readme',
  ]
)

python_library(
  name = 'python_setup',
  sources = ['python_setup.py'],
  dependencies = [
    'src/python/pants/base:config',
  ]
)

python_library(
  name = 'antlr_builder',
  sources = ['antlr_builder.py'],
  dependencies = [
    ':code_generator',
    '3rdparty/python:antlr-3.1.3',
    'src/python/pants/ivy',
    'src/python/pants/util:dirutil',
  ]
)

python_library(
  name = 'binary_builder',
  sources = ['binary_builder.py'],
  dependencies = [
    ':code_generator',
    ':python_chroot',
    '3rdparty/python:pex',
    'src/python/pants/base:config',
    'src/python/pants/backend/python/targets:python',
  ]
)

python_library(
  name = 'code_generator',
  sources = ['code_generator.py'],
  dependencies = [
    ':sdist_builder',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
  ]
)


python_library(
  name = 'interpreter_cache',
  sources = ['interpreter_cache.py'],
  dependencies = [
    ':python_setup',
    ':resolver',
    '3rdparty/python:pex',
    '3rdparty/python:setuptools',
    'src/python/pants/util:dirutil',
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
    ':binary_builder',
    ':python_chroot',
    ':test_builder',
    'src/python/pants/backend/python/targets:python',
  ],
)

python_library(
  name = 'python_chroot',
  sources = ['python_chroot.py'],
  dependencies = [
    ':antlr_builder',
    ':python_requirement',
    ':python_setup',
    ':resolver',
    ':thrift_builder',
    '3rdparty/python:pex',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.decorators',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:config',
    'src/python/pants/base:target',
    'src/python/pants/base:build_invalidator',
    'src/python/pants/util:dirutil'
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
    ':python_setup',
    '3rdparty/python:pex',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/python/targets:python',
  ],
)

python_library(
  name = 'sdist_builder',
  sources = ['sdist_builder.py'],
  dependencies = [
    '3rdparty/python:pex',
  ]
)

python_library(
  name = 'test_builder',
  sources = ['test_builder.py'],
  dependencies = [
    ':python_chroot',
    # NOTE(pl): We must pull in coverage by hand even though it isn't imported.
    # pytest-cov otherwise pulls in a newer version of coverage that doesn't
    # work in all environments, notably some OSX installs.
    '3rdparty/python:coverage',
    '3rdparty/python:pex',
    '3rdparty/python:pytest',
    '3rdparty/python:pytest-cov',
    '3rdparty/python/twitter/commons:twitter.common.lang',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:config',
    'src/python/pants/base:target',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'thrift_builder',
  sources = ['thrift_builder.py'],
  dependencies = [
    ':code_generator',
    'src/python/pants/backend/codegen/targets:python',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_environment',
    'src/python/pants:thrift_util',
    'src/python/pants/util:dirutil',
  ]
)
