node_module(
  name='node-thrift-js-test',
  sources=globs('package.json', 'yarn.lock', '.babelrc', 'test/*.js'),
  package_manager='yarn',
  dependencies=[
    'contrib/node/examples/src/node/employee-dep'
  ],
)

node_test(
  name='mocha',
  dependencies=[
    ':node-thrift-js-test'
  ],
)
