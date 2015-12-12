# This project uses the node_preinstalled_module type, which is an example to show
# an alternative Node module resolver.

node_preinstalled_module(
  name='preinstalled-project',
  sources=globs('package.json', 'src/*.js', 'test/*.js'),
  dependencies_archive_url=('https://raw.githubusercontent.com/pantsbuild/'
    'node-preinstalled-modules/master/node_modules.tar.gz')
)

node_test(
  name='unit',
  dependencies=[
    ':preinstalled-project'
  ]
)
