load("//examples/src/scala/org/pantsbuild/example/build_file_macros/BUILD_MACROS", "my_func")
#def my_func():
#    return ['examples/src/scala/org/pantsbuild/example/hello/welcome:welcome']


def my_source():
  return 'Exe.scala'

jvm_binary(
  main="org.pantsbuild.example.build_file_macros.Exe",
  source=my_source(),
  dependencies=my_func()
)
