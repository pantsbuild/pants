target(
  name='all',
  dependencies=[
    ':docsitegen',
  ],
)

python_library(
  name='docsitegen',
  sources=['docsitegen.py'],
  dependencies=[
    'src/python/internal_backend/docsite:PyYAML',
    'src/python/internal_backend/docsite:beautifulsoup4',
    'src/python/pants/base:exceptions',
    'src/python/pants/backend/core/tasks:task',
  ]
)