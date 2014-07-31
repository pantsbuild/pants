# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# common rev for all com.google.guava%guava* artifacts
GUAVA_REV='16.0'

jar_library(
  name='guava',
  jars=[
    jar(
      org='com.google.guava', name='guava', rev=GUAVA_REV,
      apidocs= 'http://docs.guava-libraries.googlecode.com/git-history/%s/javadoc/' % GUAVA_REV
    ).with_sources().with_docs(),

    # Defined in provided scope so we provide here
    jar(org='javax.inject', name='javax.inject', rev='1').with_sources(),
  ],
  dependencies=[
    ':jsr305',
  ],
)

jar_library(
  name='jsr305',
  jars=[
    jar(org='com.google.code.findbugs', name='jsr305', rev='1.3.9'),
  ]
 )
