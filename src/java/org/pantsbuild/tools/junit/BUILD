# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='junit',
  provides=artifact(
    org='org.pantsbuild',
    name='junit-runner',
    repo=public,
    publication_metadata=pants_library("""
      A command line tool for running junit tests that provides functionality above and beyond
      that provided by org.junit.runner.JUnitCore.
    """)
  ),
  dependencies=[
    '3rdparty:args4j',
    '3rdparty:guava',
    '3rdparty:junit',
    '3rdparty/jvm/commons-io:commons-io',
    'src/java/org/pantsbuild/args4j',
    'src/java/org/pantsbuild/junit/annotations',
    'src/java/org/pantsbuild/tools/junit/withretry',
  ],
  sources=globs('*.java', 'impl/*.java')
)

jvm_binary(
  name='main',
  basename='junit-runner',
  main='org.pantsbuild.tools.junit.ConsoleRunner',
  dependencies=[
    ':junit',
  ],
deploy_jar_rules = jar_rules(rules=[
      Skip(r'^LICENSE$'),
      Skip(r'^license'),
      Skip(r'^META-INF/[^/]+\.SF$'),
      Skip(r'^META-INF/[^/]+\.DSA$'),
      Skip(r'^META-INF/[^/]+\.RSA$'),
      Skip(r'^META-INF/INDEX.LIST$'),
      Skip(r'^META-INF/LICENSE$'),
      Duplicate(apply_pattern=r'^META-INF/services/', action= Duplicate.CONCAT_TEXT)
  ]),
  description="""
A replacement for org.junit.runner.JUnitCore.main that adds:
  + support for running individual test methods using [classname]#[methodname]
  + support for stderr and stdout redirection for tests
  + support for ant style junit-report xml output
  + support for per test class timer
  + support for running test classes in parallel
"""
)
