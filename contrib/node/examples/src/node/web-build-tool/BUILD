# dev_dependency is set to True.  This module will not be included in any JS bundle or JVM binary.
node_module(
  sources=globs('package.json','web-build-tool','webpack.config.base.js'),
  dependencies=[
    'contrib/node/examples/3rdparty/node/babel-loader',
    'contrib/node/examples/3rdparty/node/css-loader',
    'contrib/node/examples/3rdparty/node/null-loader',
    'contrib/node/examples/3rdparty/node/style-loader',
    'contrib/node/examples/3rdparty/node/webpack',
  ],
  dev_dependency=True,
)
