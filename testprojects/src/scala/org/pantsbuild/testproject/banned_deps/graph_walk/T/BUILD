scala_library(
  name = "T",
  dependencies=[
    "testprojects/src/scala/org/pantsbuild/testproject/banned_deps/graph_walk/D1",
    "testprojects/src/scala/org/pantsbuild/testproject/banned_deps/graph_walk/D2",
    "testprojects/src/scala/org/pantsbuild/testproject/banned_deps/graph_walk/D3"
  ],
  dependency_constraints=
      DependencyConstraints([
              Tag("deprecated")
          ]),
)

