node_module(
  name='npm-path-injection',
  sources=globs('package.json', 'npm-shrinkwrap.json', '.babelrc', 'test/*.js'),
  package_manager='npm',
)

node_test(
  name='mocha',
  dependencies=[
    ':npm-path-injection'
  ]
)
