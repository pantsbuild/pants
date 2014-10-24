page(
  name='readme',
  source='readme.md',
  dependencies=[
    ':credits',
    ':dev_tasks',
    ':docs',
    ':howto_ask',
    ':howto_contribute',
    ':howto_customize',
    ':howto_develop',
    ':howto_plugin',
    ':intellij',
    ':internals',
    ':release',
  ]
)

page(
  name='credits',
  source='credits.md',
)

page(
  name='dev_tasks',
  source='dev_tasks.md',
)

page(
  name='dev_tasks_publish_extras',
  source='dev_tasks_publish_extras.md',
)

page(
  name='docs',
  source='docs.md',
)

page(
  name='howto_ask',
  source='howto_ask.md',
)

page(
  name='howto_contribute',
  source='howto_contribute.md',
  dependencies=[
    ':docs',
    ':howto_ask',
    ':howto_develop',
    ':internals',
  ]
)

page(
  name='howto_customize',
  source='howto_customize.md',
  dependencies=[
    ':howto_contribute',
    ':howto_plugin'
  ]
)

page(
  name='howto_develop',
  source='howto_develop.md',
  dependencies=[
    ':howto_contribute',
    'src/docs:first_tutorial',
  ]
)

page(
  name='howto_plugin',
  source='howto_plugin.md',
  dependencies=[
    ':docs',
    ':howto_develop',
  ]
)

page(
  name='intellij',
  source='intellij.md',
  dependencies=[
    'src/docs:with_intellij',
  ])

page(
  name='internals',
  source='internals.md',
  dependencies=[
    ':dev_tasks',
    'src/docs:first_concepts',
    'src/python/pants/docs:dev_tasks',
  ]
)

page(
  name='release',
  source='release.md',
)

