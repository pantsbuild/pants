python_library(
  name = 'all',
  dependencies = [
    pants(':git'),
  ]
)

python_library(
  name = 'scm',
  sources = ['__init__.py'],
  dependencies = [
    pants('src/python/twitter/common/lang'),
  ],
)

python_library(
  name = 'git',
  sources = ['git.py'],
  dependencies = [
    pants(':scm'),
    pants('src/python/twitter/common/log'),
  ],
)
