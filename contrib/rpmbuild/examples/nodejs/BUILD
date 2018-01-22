
# NOTE(mateo): See the README for directions on how to update the nodejs version.

node_ver='v8.2.1'

remote_rpm_source(
  name='node.tar.gz',
  version=node_ver,
)

# This creates several nodejs packages and are all named nodejs-distribution* to disambiguate from public RPMs.
rpm_package(
  name='nodejs',
  spec='nodejs.spec',
  sources=[
    'SOURCES/node-js.node.gyp-python27.patch',
    'SOURCES/node-js.v8_inspector.gyp.patch',
  ],
  defines={
    'version': node_ver,
    'release': '0',
  },
  dependencies = [
    ':node.tar.gz',
  ]
)
