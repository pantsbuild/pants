node_module(
  name='yarnpkg-path-injection',
  sources=globs('package.json', 'yarn.lock', '.babelrc', 'test/*.js'),
  package_manager='yarn',
)

node_test(
  name='mocha',
  dependencies=[
    ':yarnpkg-path-injection'
  ]
)
