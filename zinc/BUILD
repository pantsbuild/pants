target(name='zinc',
  dependencies=[
    'src/scala/org/pantsbuild/zinc'
  ]
)

jvm_binary(
  name='bin',
  basename='zinc',
  main='org.pantsbuild.zinc.Main',
  dependencies=[
    ':zinc'
  ]
).with_description("zinc -- the scala compiler in nailgun")
