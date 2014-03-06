page(
  name = 'readme',
  source = 'README.md',
  dependencies = [
    pants('src/python/twitter/pants:readme'),
  ]
)

python_library(
  name = 'python_setup',
  sources = ['python_setup.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:config'),
  ]
)

python_library(
  name = 'antlr_builder',
  sources = ['antlr_builder.py'],
  dependencies = [
    pants(':code_generator'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/ivy'),
  ]
)

python_library(
  name = 'binary_builder',
  sources = ['binary_builder.py'],
  dependencies = [
    pants(':code_generator'),
    pants(':python_chroot'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/targets:python'),
  ]
)

python_library(
  name = 'code_generator',
  sources = ['code_generator.py'],
  dependencies = [
    pants(':sdist_builder'),
    pants('src/python/twitter/common/dirutil'),
  ]
)


python_library(
  name = 'interpreter_cache',
  sources = ['interpreter_cache.py'],
  dependencies = [
    pants('3rdparty/python:setuptools'),
    pants(':python_setup'),
    pants(':resolver'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/python'),
  ]
)

python_library(
  name = 'python_builder',
  sources = ['python_builder.py'],
  dependencies = [
    pants(':binary_builder'),
    pants(':python_chroot'),
    pants(':test_builder'),
    pants('src/python/twitter/pants/targets:python'),
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
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/decorators'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/common/quantity'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/base:build_invalidator'),
    pants('src/python/twitter/pants/targets:python'),
  ],
)

python_library(
  name = 'resolver',
  sources = ['resolver.py'],
  dependencies = [
    pants(':python_setup'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/pants/targets:python'),
  ],
)

python_library(
  name = 'sdist_builder',
  sources = ['sdist_builder.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/python'),
  ]
)

python_library(
  name = 'test_builder',
  sources = ['test_builder.py'],
  dependencies = [
    pants(':python_chroot'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/quantity'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:python'),
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
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/targets:python'),
    pants('src/python/twitter/pants:thrift_util'),
  ]
)
