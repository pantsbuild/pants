node_module(
  name='default_lockfiles',
  sources=globs('package.json', 'yarn.lock', '.babelrc', 'index.js'),
  package_manager='yarn',
)

node_module(
  name='custom_lockfile',
  sources=globs('custom_lockfile', 'package.json', 'yarn.lock', '.babelrc', 'index.js'),
  package_manager='yarn',
  package_lockfiles=[
    'custom_lockfile'
  ]
)

node_module(
  name='custom_lockfile_outside_sources',
  sources=globs('custom_lockfile', 'package.json', 'yarn.lock', '.babelrc', 'index.js'),
  package_manager='yarn',
  package_lockfiles=['custom_lockfile_not_in_sources'],
)
