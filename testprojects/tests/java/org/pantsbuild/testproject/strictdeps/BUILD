java_library(
  name='A1',
  sources = ['A.java'],
  dependencies=[':B'],
  strict_deps=True,
)

java_library(
  name='A2',
  sources = ['A.java'],
  dependencies=[':B'],
  strict_deps=False,
)

java_library(
  name='A3',
  sources = ['A.java'],
  dependencies=[':B'],
)

java_library(
  name='A4',
  sources = ['A.java'],
  dependencies=[':B1'],
)

java_library(
  name='B',
  sources = ['B.java'],
  dependencies=[':C'],
)

java_library(
  name='B1',
  sources = ['B.java'],
  dependencies=[':C'],
  strict_deps=True,
)

java_library(
  name='C',
  sources = ['C.java'],
  dependencies=[':D'],
)

java_library(
  name='C1',
  sources = ['C.java'],
  dependencies=[':E'],
  strict_deps=True,
)

java_library(
  name='D',
  sources = ['D.java'],
)

target(
  name='E',
  dependencies=[':D'],
)
