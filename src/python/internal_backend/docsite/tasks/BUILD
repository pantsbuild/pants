target(
  name='all',
  dependencies=[
    ':docsitegen',
  ],
)

python_requirements()

python_library(
  name='docsitegen',
  sources=['docsitegen.py'],
  dependencies=[
    ':PyYAML',
    ':beautifulsoup4',
    'src/python/pants/base:exceptions',
    'src/python/pants/backend/core/tasks:task',
  ]
)