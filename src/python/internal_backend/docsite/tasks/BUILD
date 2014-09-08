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
    'src/python/pants/backend/core/tasks:task',
  ]
)