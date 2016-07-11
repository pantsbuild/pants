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
                  apidocs='http://google.github.io/guava/releases/18.0/api/docs/')
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
              jar(org='com.puppycrawl.tools', name='checkstyle', rev='5.5',
                  excludes=[
                    exclude(org='com.google.collections', name='google-collections'),
                  ])
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

jar_library(name='log4j',
            jars = [
              jar(org='log4j', name='log4j', rev='1.2.15',
                  excludes=[
                    exclude(org='jline', name='jline'),
                    exclude(org='javax.jms', name='jms'),
                    exclude(org='com.sun.jdmk', name='jmxtools'),
                    exclude(org='com.sun.jmx', name='jmxri'),
                  ])
            ])

jar_library(name='protobuf-2.4.1',
            jars = [
              jar(org='com.google.protobuf', name='protobuf-java', rev='2.4.1'),
            ],
            # javac requires protobuf to be present in order to compile the MessageBuilders API.
            scope='forced',)

target(name='protobuf-java', dependencies = [':protobuf-2.4.1'])

jar_library(name='protobuf-test-import',
            jars = [
              jar(org='com.squareup.testing.protolib', name='protolib-test', rev='1.0.1'),
            ])

jar_library(name='scrooge-core',
            jars = [
              # used by scrooge-generator in BUILD.tools:scrooge-gen
              scala_jar(org='com.twitter', name='scrooge-core', rev='3.20.0'),
            ])

jar_library(name='shapeless',
            jars=[
              scala_jar(org='com.chuusai', name='shapeless', rev='2.2.5'),
            ])

jar_library(name='slf4j-api',
            jars = [
              jar(org='org.slf4j', name='slf4j-api', rev='1.6.1'),
            ])

# NB: we have two versions of thrift here due to scrooge requiring one version while apache
# thrift requires another. This is not usually recommended.
jar_library(name='libthrift-0.9.2',
            jars = [
              jar(org='org.apache.thrift', name='libthrift', rev='0.9.2')
            ],
            # javac uses undeclared types to build the MessageBuilder API.
            scope='forced',)

target(name='thrift-0.9.2', dependencies = [':libthrift-0.9.2'])

jar_library(name='libthrift-0.6.1',
            jars = [
              jar(org='org.apache.thrift', name='libthrift', rev='0.6.1')
            ])

target(name='thrift-0.6.1',
       dependencies = [
         ':commons-lang',
         ':libthrift-0.6.1',
         ':slf4j-api',
       ])


###############
# Test support
#

jar_library(name='easymock',
            jars=[
              jar('org.easymock', 'easymock', '3.3.1')
            ])

jar_library(name='gson',
	    jars = [
	      jar(org='com.google.code.gson', name='gson', rev='2.3.1')
	    ])

jar_library(name='guava-testlib',
            jars=[
              jar('com.google.guava', 'guava-testlib', '18.0')
            ])

jar_library(name='junit',
            jars=[
              jar('junit', 'junit', '4.12')
            ],
            # junit is frequently used only for its annotations.
            scope='forced',)

jar_library(name='scalatest',
            jars=[
              scala_jar('org.scalatest', 'scalatest', '2.2.4')
            ])

jar_library(name='wire-runtime',
            jars=[
              jar(org='com.squareup.wire', name='wire-runtime', rev='1.8.0'),
            ],
            # javac uses undeclared types to build the MessageBuilder API.
            scope='forced',)
