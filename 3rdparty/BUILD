# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This BUILD file defines common external library dependencies used across many modules.  Modules
# can use these jar_library deps by specifying '3rdparty:[name]' in their dependencies list.
# If you're looking at this BUILD file for inspiration organizing your own project's 3rdparty
# directory, note that for a multi-project workspace, we suggest setting up a tree of directories,
# as detailed at http://pantsbuild.github.io/3rdparty.html .

# To add dependency for a JVM-tool needed by Pants itself (e.g., Antlr),
# see http://pantsbuild.github.io/dev_tasks.html#jvm-tool-bootstrapping

###################
# Production libs
#

jar_library(name='args4j',
            jars=[
              jar('args4j', 'args4j', '2.32')
            ])

jar_library(name='guava',
            jars=[
              jar('com.google.guava', 'guava', '18.0',
                  apidocs='http://docs.guava-libraries.googlecode.com/git-history/v18.0/javadoc/'),
            ])

jar_library(name='jansi',
            jars=[
              jar('org.fusesource.jansi', 'jansi', '1.11'),
            ])

jar_library(name='jsr305',
            jars=[
              jar('com.google.code.findbugs', 'jsr305', '3.0.0'),
            ])

jar_library(name='checkstyle',
            jars = [
              jar(org='com.puppycrawl.tools', name='checkstyle', rev='5.5')
                .exclude(org='com.google.collections', name='google-collections'),
            ],
            dependencies = [
              # Needs this as the replacement for the excluded google-collections.
              ':guava',
            ])

jar_library(name='commons-lang',
            jars = [
              jar(org='commons-lang', name='commons-lang', rev='2.5'),
            ])


jar_library(name='cucumber-java',
            jars=[
              jar(org='info.cukes', name='cucumber-java', rev='1.1.7'),
            ])

# common rev for all com.twitter%finagle* artifacts
FINAGLE_REV = '6.24.0'

jar_library(name='finagle-core',
            jars = [
              jar(org='com.twitter', name='finagle-core_2.10', rev=FINAGLE_REV),
            ],
            dependencies = [
              ':util-core'
            ])

# The finagle-thrift lib has a dep on org.apache.thrift#libthrift;0.5.0 which is
# hosted at maven.twttr.com.  Since finagle-thrift is only used by test code we
# exclude and then use org.apache.hadoop#libthrift;0.5.0.o instead to avoid the
# need to setup a custom ivy resolver.
jar_library(name='finagle-thrift',
            jars = [
              jar(org='com.twitter', name='finagle-thrift_2.10', rev=FINAGLE_REV)
                .exclude(org='org.apache.thrift', name='libthrift'),
            ],
            dependencies=[
              ':libthrift-0.5.0',
            ])

jar_library(name='log4j',
            jars = [
              jar(org='log4j', name='log4j', rev='1.2.15')
                .exclude(org='jline', name='jline')
                .exclude(org='javax.jms', name='jms')
                .exclude(org='com.sun.jdmk', name='jmxtools')
                .exclude(org='com.sun.jmx', name='jmxri'),
            ])

jar_library(name='protobuf-2.4.1',
            jars = [
              jar(org='com.google.protobuf', name='protobuf-java', rev='2.4.1'),
            ])

jar_library(name='protobuf-java',
            dependencies = [
              ':protobuf-2.4.1'
            ])

jar_library(name='protobuf-test-import',
            jars = [
              jar(org='com.squareup.testing.protolib', name='protolib-test', rev='1.0.1'),
            ])

jar_library(name='scrooge-core',
            jars = [
              # used by scrooge-generator in BUILD.tools:scrooge-gen
              jar(org='com.twitter', name='scrooge-core_2.10', rev='3.17.0'),
            ])

jar_library(name='shapeless',
            jars=[
              jar(org='com.chuusai', name='shapeless_2.10.4', rev='2.0.0'),
            ])

jar_library(name='slf4j-api',
            jars = [
              jar(org='org.slf4j', name='slf4j-api', rev='1.6.1'),
            ])

jar_library(name = 'spindle-runtime',
            jars = [
              jar(org = 'com.foursquare', name = 'spindle-runtime_2.10', rev = '3.0.0-M7'),
            ])

jar_library(name='libthrift-0.5.0',
            jars = [
              jar(org='org.apache.hadoop', name='libthrift', rev='0.5.0.0')
                # These are un-needed and un-available log4j appender deps pulled in via a
                # libthrift dep on slf4j-log4j.
                .exclude(org='javax.jms', name='jms')
                .exclude(org='com.sun.jdmk', name='jmxtools')
                .exclude(org='com.sun.jmx', name='jmxri')
            ])

jar_library(name='thrift-0.5.0',
            dependencies = [
              ':commons-lang',
              ':libthrift-0.5.0',
              ':slf4j-api',
            ])

jar_library(name='thrift-0.5.0-finagle',
            dependencies = [
              ':thrift-0.5.0',

              # finagle thrift extra deps
              ':finagle-core',
              ':finagle-thrift',
              ':util-core',
            ])

jar_library(name='thrift',
            dependencies = [ ':thrift-0.5.0' ])

# common rev for all com.twitter%util* artifacts
UTIL_REV = '6.23.0'

jar_library(name='util-core',
            jars = [
              jar(org='com.twitter', name='util-core_2.10', rev=UTIL_REV),
            ])


###############
# Test support
#

jar_library(name='easymock',
            jars=[
              jar('org.easymock', 'easymock', '3.3.1')
            ])

jar_library(name='guava-testlib',
            jars=[
              jar('com.google.guava', 'guava-testlib', '18.0')
            ])

jar_library(name='junit',
            jars=[
              jar('junit', 'junit', '4.12')
            ])

jar_library(name='specs',
            jars=[
              jar('org.scala-tools.testing', 'specs_2.10', '1.6.9')
            ])
