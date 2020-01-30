node_module(
  sources=['package.json', 'yarn.lock', 'index.js', 'test/*.js', 'cli.js'],
  package_manager='yarn',
  bin_executables = {
    'add-one': 'cli.js'
  },
)

node_test(
  name='add-one-test',
  script_name='test',
  dependencies=[
    ':add-one'
  ]
)
