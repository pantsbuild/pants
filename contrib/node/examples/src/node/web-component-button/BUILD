node_module(
  name='web-component-button',
  sources=globs('package.json', 'webpack.config.js', 'src/*', 'test/*'),
  dependencies=[
    'contrib/node/examples/3rdparty/node/mocha',
    'contrib/node/examples/3rdparty/node/react',
    'contrib/node/examples/src/node/web-build-tool',
  ]
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
