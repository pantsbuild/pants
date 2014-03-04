python_tests(
  name = 'cache',
  sources = globs('*.py'),
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:build_invalidator'),
    pants('src/python/twitter/pants/cache'),
    pants('tests/python/twitter/pants/testutils'),
  ]
)
