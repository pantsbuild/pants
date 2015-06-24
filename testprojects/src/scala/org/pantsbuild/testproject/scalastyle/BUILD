scala_library(
  name = 'lib1',
  sources = ['File1.scala']
)

scala_library(
  name = 'lib2',
  sources = ['File2.scala'],
  dependencies = [
    'testprojects/src/scala/org/pantsbuild/testproject/scalastyle:lib1'
  ]
)

scala_library(
  name = 'lib3',
  sources = ['File3.scala']
)
