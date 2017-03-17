java_library(
  name='A',
  sources = ['A.java'],
)

java_library(
  name='B',
  sources = ['B.java'],
  dependencies=[':A'],
  exports=[':A'],
  strict_deps=True,
)

java_library(
  name='C',
  sources = ['C.java'],
  dependencies=[':B'],
  exports=[':B'],
  strict_deps=True,
)

java_library(
  name='D',
  sources = ['D.java'],
  dependencies=[':C'],
  strict_deps=True,
)
