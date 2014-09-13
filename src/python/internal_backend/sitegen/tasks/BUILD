target(
  name='all',
  dependencies=[
    ':sitegen',
  ],
)

python_library(
  name='sitegen',
  sources=['sitegen.py'],
  dependencies=[
    'src/python/internal_backend/sitegen:PyYAML',
    'src/python/internal_backend/sitegen:beautifulsoup4',
    'src/python/pants/base:exceptions',
    'src/python/pants/backend/core/tasks:task',
  ]
)