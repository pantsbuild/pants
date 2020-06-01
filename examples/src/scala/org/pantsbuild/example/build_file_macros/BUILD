load("//examples/src/scala/org/pantsbuild/example/build_file_macros/BUILD_MACROS", "dep_on_welcome")
load("examples/src/scala/org/pantsbuild/example/build_file_macros/BUILD_MACROS_2", "source_exe_scala")

jvm_binary(
  main="org.pantsbuild.example.build_file_macros.Exe",
  source=source_exe_scala(),
  dependencies=dep_on_welcome()
)
