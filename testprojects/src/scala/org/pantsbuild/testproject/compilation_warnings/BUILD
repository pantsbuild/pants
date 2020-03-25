scala_library(
  name='nonfatal',
  compiler_option_sets={},
  sources=['Warning.scala'],
)

# TODO these should be merged if we decide to remove `-Xfatal_warnings` from the compiler option set
scala_library(
  name='fatal_compiler_options',
  compiler_option_sets={'fatal_warnings'},
  sources=['Warning.scala'],
)

scala_library(
  name='fatal_explicit',
  fatal_warnings=True,
  sources=['Warning.scala'],
)
