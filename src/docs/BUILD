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
    ':3rdparty',
    ':announce_201409',
    ':build_files',
    ':first_concepts',
    ':first_tutorial',
    ':install',
    ':publish',
    ':setup_repo',
    'examples/src/java/com/pants/examples:readme',
    'examples/src/python/example:readme',
    'examples/src/thrift/com/pants/examples:readme',
    'src/python/pants/docs:readme',
    ])

page(
  name='invoking',
  source='invoking.md',
  dependencies=[
    ':first_tutorial',
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
  source='setup_repo.md',
  dependencies=[
    ':first_concepts',
    ':publish',
    'src/python/pants/docs:dev_tasks',
    'src/python/pants/docs:dev_tasks_publish_extras',
    'src/python/pants/docs:howto_contribute',
    'src/python/pants/docs:howto_plugin',
  ]
)

page(
  name='target_addresses',
  source='target_addresses.md'
)

page(
  name='tshoot',
  source='tshoot.md',
  dependencies=[
    'src/python/pants/docs:howto_ask',
  ]
)

page(
  name='with_emacs',
  source='with_emacs.md'
)

page(
  name='with_intellij',
  source='with_intellij.md'
)
