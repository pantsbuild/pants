# No build script specified. Dependents will include raw installation results:
# src/*, package.json and node_modules installed by mocha.
node_module(
  sources=globs('package.json', 'src/*'),
  dependencies=[
    'contrib/node/examples/3rdparty/node/mocha',
  ]
)
