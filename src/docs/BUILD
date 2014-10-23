page(
  name='3rdparty',
  source='3rdparty.md',
  dependencies=[
    'examples/src/java/com/pants/examples:3rdparty_jvm',
    'examples/src/python/example:3rdparty_py',
  ],
)

page(
  name='announce_201409',
  source='announce_201409.md'
)

page(
  name='build_files',
  source='build_files.md'
)

page(
  name='first_concepts',
  source='first_concepts.md',
  dependencies=[
    ':first_tutorial',
  ]
)

page(
  name='first_tutorial',
  source='first_tutorial.md',
  dependencies=[
    ':first_concepts',
    'examples/src/java/com/pants/examples:readme',
    'examples/src/python/example:readme',
  ]
)

page(
  name='index',
  source='index.md',
  dependencies=[
    'examples/src/java/com/pants/examples:readme',
    'examples/src/python/example:readme',
    'examples/src/thrift/com/pants/examples:readme',
    'src/docs:3rdparty',
    'src/docs:announce_201409',
    'src/docs:build_files',
    'src/docs:first_concepts',
    'src/docs:first_tutorial',
    'src/docs:publish',
    'src/python/pants/docs:readme',
    ])

page(
  name='invoking',
  source='invoking.md',
  dependencies=[
    ':install',
  ]
)

page(
  name='install',
  source='install.md',
)

page(
  name='publish',
  source='publish.md'
)

page(
  name='setup_repo',
  source='setup_repo.md'
)