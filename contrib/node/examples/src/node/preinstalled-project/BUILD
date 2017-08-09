# This project uses the node_preinstalled_module type, which is an example to show
# an alternative Node module resolver.

node_preinstalled_module(
  sources=globs('package.json', 'src/*.js', 'test/*.js'),
  # TODO(John Sirois): Update https://github.com/pantsbuild/node-preinstalled-modules to have a
  # `sync-s3.sh` in place of the current `sync-bintray.sh`.
  # See: https://github.com/pantsbuild/pants/issues/4800
  dependencies_archive_url=
    'https://s3.amazonaws.com/node-preinstalled-modules.pantsbuild.org/node_modules.tar.gz'
)

node_test(
  name='unit',
  dependencies=[
    ':preinstalled-project'
  ]
)

node_bundle(
  name='preinstalled-project-bundle',
  node_module=':preinstalled-project'
)
