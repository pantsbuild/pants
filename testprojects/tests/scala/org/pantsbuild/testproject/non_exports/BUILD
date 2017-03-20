scala_library(
  name='A',
  sources = ['A.scala'],
)

scala_library(
  name='B',
  sources = ['B.scala'],
  dependencies=[':A'],
  strict_deps=True,
)

scala_library(
  name='C',
  sources = ['C.scala'],
  dependencies=[':B'],
  strict_deps=True,
)
