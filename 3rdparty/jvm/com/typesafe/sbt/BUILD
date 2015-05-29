SBT_REV = '0.13.8'

# We erect this dep by summing up intransitive jars with our local scala-{compiler,library} version.
# TODO(John Sirois): Why do we do this really?  Can the intransitive go?  If our
# scala-{compiler,library} is > than sbts, highest wins _anyway_ ... so does this mean we're
# guarding against having a lower version of scala-{compiler,library} than sbt?
jar_library(
  name='incremental-compiler',
  jars=[
    jar(org='com.typesafe.sbt', name='incremental-compiler', rev=SBT_REV, intransitive=True),
  ],
  dependencies=[
    '//:sbt-interface',
    '//:scala-compiler',
    '//:scala-library',
  ]
)
