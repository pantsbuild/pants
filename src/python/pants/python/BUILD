# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
    pants('src/python/pants/BUILD.commons:twitter.common.dirutil'),
    pants('src/python/pants/ivy'),
  ]
)

python_library(
  name = 'binary_builder',
  sources = ['binary_builder.py'],
  dependencies = [
    pants(':code_generator'),
    pants(':python_chroot'),
    pants('src/python/pants/BUILD.commons:twitter.common.python'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/targets:python'),
  ]
)

python_library(
  name = 'code_generator',
  sources = ['code_generator.py'],
  dependencies = [
    pants(':sdist_builder'),
    pants('src/python/pants/BUILD.commons:twitter.common.dirutil'),
  ]
)


python_library(
  name = 'interpreter_cache',
  sources = ['interpreter_cache.py'],
  dependencies = [
    pants('3rdparty/python:setuptools'),
    pants(':python_setup'),
    pants(':resolver'),
    pants('src/python/pants/BUILD.commons:twitter.common.dirutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.python'),
  ]
)

python_library(
  name = 'python_builder',
  sources = ['python_builder.py'],
  dependencies = [
    pants(':binary_builder'),
    pants(':python_chroot'),
    pants(':test_builder'),
    pants('src/python/pants/targets:python'),
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
    pants('src/python/pants/BUILD.commons:twitter.common.collections'),
    pants('src/python/pants/BUILD.commons:twitter.common.decorators'),
    pants('src/python/pants/BUILD.commons:twitter.common.dirutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.python'),
    pants('src/python/pants/BUILD.commons:twitter.common.quantity'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:build_invalidator'),
    pants('src/python/pants/targets:python'),
  ],
)

python_library(
  name = 'resolver',
  sources = ['resolver.py'],
  dependencies = [
    pants(':python_setup'),
    pants('src/python/pants/BUILD.commons:twitter.common.collections'),
    pants('src/python/pants/BUILD.commons:twitter.common.python'),
    pants('src/python/pants/targets:python'),
  ],
)

python_library(
  name = 'sdist_builder',
  sources = ['sdist_builder.py'],
  dependencies = [
    pants('src/python/pants/BUILD.commons:twitter.common.contextutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.python'),
  ]
)

python_library(
  name = 'test_builder',
  sources = ['test_builder.py'],
  dependencies = [
    pants(':python_chroot'),
    pants('src/python/pants/BUILD.commons:twitter.common.collections'),
    pants('src/python/pants/BUILD.commons:twitter.common.contextutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.dirutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.lang'),
    pants('src/python/pants/BUILD.commons:twitter.common.quantity'),
    pants('src/python/pants/BUILD.commons:twitter.common.python'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:python'),
    pants('3rdparty/python:coverage'),
    pants('3rdparty/python:pytest'),
    pants('3rdparty/python:pytest-cov'),
  ],
)

python_library(
  name = 'thrift_builder',
  sources = ['thrift_builder.py'],
  dependencies = [
    pants(':code_generator'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/targets:python'),
    pants('src/python/pants:thrift_util'),
  ]
)
