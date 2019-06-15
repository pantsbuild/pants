scala_library(
  dependencies=[
    'contrib/bloop/3rdparty:ammonite-ops',
    'contrib/bloop/3rdparty:bloop-json-config',
    'contrib/bloop/3rdparty:spray-json',
  ],
)

jvm_binary(
  name='bloop-config-gen',
  main='pants.contrib.bloop.BloopConfigGen',
  dependencies=[
    ':bloop',
  ],
)
