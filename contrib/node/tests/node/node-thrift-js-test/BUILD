node_module(
  name='node-thrift-js-test',
  sources=globs('package.json', 'yarn.lock', '.babelrc', 'test/*.js'),
  package_manager='yarn',
  dependencies=[
    'contrib/node/examples/src/node/employee-dep:employee-dep'
  ],
)

# TODO(#8168): Make JS test compatible with newer Mocha versions.
node_test(
  name='mocha',
  dependencies=[
    ':node-thrift-js-test'
  ],
)
