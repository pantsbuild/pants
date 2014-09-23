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
    '3rdparty/python/internal_backend:beautifulsoup4',
    'src/python/pants/base:exceptions',
    'src/python/pants/backend/core/tasks:task',
  ]
)