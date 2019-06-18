scala_library(
  provides=scala_artifact(
    org='org.pantsbuild',
    name='bloop-compile-wrapper',
    repo=public,
    publication_metadata=pants_library('???'),
  ),
  dependencies=[
    '3rdparty/jvm/org/scala-sbt:util-logging',
    # 'contrib/bloop/3rdparty/jvm:bsp4s',
    'contrib/bloop/3rdparty/jvm:bloop-frontend',
    'contrib/bloop/3rdparty/jvm:bloop-launcher',
    # 'contrib/bloop/3rdparty/jvm:circe',
    # 'contrib/bloop/3rdparty/jvm:lsp4s',
    # 'contrib/bloop/3rdparty/jvm:monix',
    # 'contrib/bloop/3rdparty/jvm:scalameta',
  ],
)

# jvm_binary(
#   name='bloop-compile-wrapper',
#   main='pants.contrib.bloop.compile.PantsCompileMain',
#   dependencies=[
#     ':compile',
#   ],
# )

# jvm_app(
#   name='bloop-compile-app',
#   deployjar=True,
#   binary=':bloop-compile-wrapper',
# )
