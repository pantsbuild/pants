# web-component-button target installs all node module dependencies but does not run webpack
# transpile since there is no build_script declared.
node_module(
  name='web-component-button',
  sources=globs('package.json', 'webpack.config.js', 'src/*', 'test/*'),
  dependencies=[
    'contrib/node/examples/3rdparty/node/mocha',
    'contrib/node/examples/3rdparty/node/react',
    'contrib/node/examples/src/node/web-build-tool',
  ],
)

node_test(
  name='unit',
  script_name='test_unit',
  dependencies=[
    ':web-component-button'
  ]
)

node_test(
  name='integration',
  script_name='test_integration',
  dependencies=[
    ':web-component-button'
  ],
  tags={'integration'},
)

# Contains non-transpiled codes including all subdirectories under node_modules dirctory.
node_bundle(
  name='web-component-button-bundle',
  node_module=':web-component-button'
)

# web-component-button-processed target invokes webpack transpiling via build_script.
node_module(
  name='web-component-button-processed',
  sources=globs('package.json', 'webpack.config.js', 'src/*', 'test/*'),
  dependencies=[
    'contrib/node/examples/3rdparty/node/mocha',
    'contrib/node/examples/3rdparty/node/react',
    'contrib/node/examples/src/node/web-build-tool',
  ],
  build_script='build',
)

# Contains transpiled codes.
node_bundle(
  name='web-component-button-processed-bundle',
  node_module=':web-component-button-processed'
)

# Used to testing dependencies bundling.
node_module(
  name='web-component-button-processed-with-dependency-artifacts',
  sources=globs('package.json', 'webpack.config.js', 'src/*', 'test/*'),
  dependencies=[
    'contrib/node/examples/3rdparty/node/mocha',
    'contrib/node/examples/3rdparty/node/react',
    'contrib/node/examples/src/node/web-build-tool',
    'contrib/node/examples/src/node/web-dependency-test',
  ],
  build_script='build',
)
