scala_library(
  name='A',
  sources = ['A.scala'],
)

scala_library(
  name='B',
  sources = ['B.scala'],
  dependencies=[':A'],
  exports=[':A'],
  strict_deps=True,
)

scala_library(
  name='C',
  sources = ['C.scala'],
  dependencies=[':B'],
  exports=[':B'],
  strict_deps=True,
)

scala_library(
  name='D',
  sources = ['D.scala'],
  dependencies=[':C'],
  strict_deps=True,
)

target(
  name='TB',
  dependencies=[':B'],
)

scala_library(
  name='TC',
  sources = ['C.scala'],
  dependencies=[':TB'],
  exports=[':TB'],
  strict_deps=True,
)

scala_library(
  name='TD',
  sources = ['D.scala'],
  dependencies=[':TC'],
  strict_deps=True,
)
