target(name='zinc',
  dependencies=[
    'src/scala/org/pantsbuild/zinc'
  ]
)

jvm_binary(
  name='bin',
  basename='zinc',
  main='com.typesafe.zinc',
  dependencies=[
    ':zinc'
  ]
).with_description("zinc -- the scala compiler in nailgun")
