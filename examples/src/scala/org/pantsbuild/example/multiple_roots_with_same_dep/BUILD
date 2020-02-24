# A and B are build graph roots, D is a shared dep.
#       A   B
#      / \ /
#     C   D
#    /
#   E


scala_library(
  name="A",
  sources=["*.scala"],
  dependencies=[":C", ":D"]
)

scala_library(
  name="B",
  sources=["*.scala"],
  dependencies=[":D"]
)

scala_library(
  name="C",
  sources=["*.scala"],
  dependencies=[":E"]
)

scala_library(
  name="D",
  sources=["*.scala"],
)

scala_library(
  name="E",
  sources=["*.scala"],
)
