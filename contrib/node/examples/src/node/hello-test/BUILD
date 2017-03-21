node_module(
  name='pantsbuild-hello-mocha',
  sources=globs('package.json', 'yarn.lock', 'npm-shrinkwrap.json', '.babelrc', 'index.js', 'test/*.js'),
  package_manager='yarn',
)

# FIXME: https://github.com/pantsbuild/pants/issues/4355
# node_test(
#   name='mocha',
#   dependencies=[
#     ':pantsbuild-hello-mocha'
#   ]
# )
