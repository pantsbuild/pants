# This project uses the node_preinstalled_module type, which is an example to show
# an alternative Node module resolver.

node_preinstalled_module(
  name='preinstalled-project',
  sources=globs('package.json', 'src/*.js', 'test/*.js'),
  url='',
  dependencies=[
    'contrib/node/examples/3rdparty/node/mocha',
  ]
)

node_test(
  name='unit',
  dependencies=[
    ':preinstalled-project'
  ]
)
