node_module(
  name='pantsbuild-hello-mocha',
  sources=['package.json', 'yarn.lock', '.babelrc', 'index.js', 'test/*.js'],
  package_manager='yarn',
)

node_test(
  name='mocha',
  dependencies=[
    ':pantsbuild-hello-mocha'
  ]
)
