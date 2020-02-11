node_module(
  sources=['package.json', 'yarn.lock', 'adder/**', 'add-two/**'],
  package_manager='yarn',
  dependencies=[
    'contrib/node/examples/src/node/yarn-workspaces/add-one',
  ],
)

node_test(
  name='test-adder',
  script_name='test-adder',
  dependencies=[
    ':yarn-workspaces'
  ]
)

node_test(
  name='test-add-two',
  script_name='test-add-two',
  dependencies=[
    ':yarn-workspaces'
  ]
)
