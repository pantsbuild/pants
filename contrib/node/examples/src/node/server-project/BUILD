# This project shows that Pants can work with a complete existing package.json for a project that
# can by installed via a normal "npm install" without Pants. In the future, Pants should understand
# package.json enough to get this benefit without any duplication.

node_module(
  name='server-project',
  sources=globs('package.json', 'checkarg', 'src/*.js', 'test/*.js'),
  dependencies=[
    'contrib/node/examples/3rdparty/node/babel',
    'contrib/node/examples/3rdparty/node/mocha',
  ]
)

node_test(
  name='unit',
  dependencies=[
    ':server-project'
  ]
)

node_test(
  name='checkarg',
  script_name='checkarg',
  dependencies=[
    ':server-project'
  ]
)
