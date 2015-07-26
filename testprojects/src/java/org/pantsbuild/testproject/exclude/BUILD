# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(name = 'nailgun-server',
  jars = [jar(org = 'com.martiansoftware', name = 'nailgun-server', rev = '0.9.1')]
)

jar_library(name = 'jmake',
  jars = [jar(org = 'org.pantsbuild', name = 'jmake', rev = '1.3.8-10')]
)

jar_library(name = 'zinc',
  jars = [
    jar(org = 'com.typesafe.zinc', name = 'zinc', rev = '0.3.7')
  ]
)

java_library(name='foo',
  sources=globs('Main.java'),
  dependencies=[
    ':zinc',
  ],
  excludes=[
    exclude('com.martiansoftware', 'nailgun-server'), # :bar depends on this
    exclude('org.pantsbuild'), # :bar depends on this
    exclude('com.typesafe.sbt', 'incremental-compiler'),
    exclude('com.typesafe.sbt', 'sbt-interface'),
  ]
)

java_library(name='bar',
  sources=globs('Main.java'),
  dependencies=[
    ':nailgun-server',
    ':jmake',
  ]
)
