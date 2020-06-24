load("//examples/src/scala/org/pantsbuild/example/build_file_macros/BUILD_MACROS", "dep_on_welcome")
# Load statements can use the `:` syntax to keep bazel compatibility. ":"s get translated to "/"
load("examples/src/scala/org/pantsbuild/example/build_file_macros:BUILD_MACROS_2", "source_exe_scala")
load("//examples/src/scala/org/pantsbuild/example/build_file_macros/CUSTOM_ARTIFACT_MACRO", "custom_artifact")

jvm_binary(
  main="org.pantsbuild.example.build_file_macros.Exe",
  sources=source_exe_scala(),
  dependencies=dep_on_welcome()
)

scala_library(
    name="provides_custom_artifact",
    sources=source_exe_scala(),
    provides=custom_artifact("provides_custom_artifact"),
)
