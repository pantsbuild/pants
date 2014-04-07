# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This BUILD file defines common external library dependencies used across many modules.  Modules
# can use these jar_library deps by specifying pants('3rdparty:[name]') in their dependencies list.

###################
# Documentation
#

page(name='readme', source='README.md')


###################
# Production libs
#

def add_log4j_excludes(jar):
  return (jar.exclude(org='jline', name='jline')
            .exclude(org='javax.jms', name='jms')
            .exclude(org='com.sun.jdmk', name='jmxtools')
            .exclude(org='com.sun.jmx', name='jmxri'))


# TODO(John Sirois): XXX only antlr2 is directly referenced by BUILDs
jar_library(name='antlr2',
            dependencies=[ jar(org='antlr', name='antlr', rev='2.7.7') ])

jar_library(name='antlr3',
            dependencies=[ jar(org='antlr', name='antlr', rev='3.1.3') ])

jar_library(name='antlr-3.4',
            dependencies=[
                jar(org='org.antlr', name='antlr', rev='3.4'),
                jar(org='org.antlr', name='antlr-runtime', rev='3.4')
             ]
           )

jar_library(name='antlr4',
            dependencies=[
                jar(org='org.antlr', name='antlr4', rev='4.1').with_sources(),
                jar(org='org.antlr', name='antlr4-runtime', rev='4.1').with_sources()
             ]
           )

jar_library(name='checkstyle',
            dependencies=[
              jar(org='com.puppycrawl.tools', name='checkstyle', rev='5.5')
                .exclude(org='com.google.collections', name='google-collections')
                .with_sources(),
              # Needs this as the replacement for the excluded google-collections.
              pants(':guava'),
            ]
           )

jar_library(name='commons-lang',
            dependencies=[
              jar(org='commons-lang', name='commons-lang', rev='2.5').with_sources()
            ]
           )


# common rev for all com.twitter%finagle* artifacts
FINAGLE_REV = '6.8.1'

jar_library(name='finagle-core',
            dependencies=[
              jar(org='com.twitter', name='finagle-core_2.9.2', rev=FINAGLE_REV)
                .with_sources(),
              pants(':util-core'),
            ])

jar_library(name='finagle-thrift',
            dependencies=[
              jar(org='com.twitter', name='finagle-thrift_2.9.2', rev=FINAGLE_REV)
            ])

# common rev for all com.google.guava%guava* artifacts
GUAVA_REV = '15.0'

jar_library(name='guava',
            dependencies=[
              jar(
                org='com.google.guava', name='guava', rev=GUAVA_REV,
                apidocs='http://docs.guava-libraries.googlecode.com/git-history/'
                          '%s/javadoc/' % GUAVA_REV
              ).with_sources().with_docs(),

              # Defined in provided scope so we provide here
              pants(':jsr305'),
              jar(org='javax.inject', name='javax.inject', rev='1').with_sources(),
            ]
           )

jar_library(name='guice',
            dependencies=[
              jar(
                org='com.google.inject', name='guice', rev='3.0',
                apidocs='http://google-guice.googlecode.com/svn/tags/3.0/javadoc/'
              ).with_sources()
            ]
           )

jar_library(name='jsr305',
            dependencies=[
              jar(org='com.google.code.findbugs', name='jsr305', rev='1.3.9')
            ]
           )

jar_library(name='log4j',
            dependencies=[
              add_log4j_excludes(jar(org='log4j', name='log4j', rev='1.2.15').with_sources())
            ])

jar_library(name='protobuf-2.4.1',
            dependencies=[
              jar(org='com.google.protobuf', name='protobuf-java', rev='2.4.1').with_sources()
            ]
           )

jar_library(name='protobuf-java',
            dependencies=[ pants(':protobuf-2.4.1') ])

jar_library(name='scala-compiler',
            dependencies=[
              jar(org='org.scala-lang', name='scala-compiler', rev='2.9.3').with_sources()
            ]
           )

jar_library(name='scala-library',
            dependencies=[
              jar(org='org.scala-lang', name='scala-library', rev='2.9.3').with_sources()
            ]
           )

jar_library(name='scrooge-core',
            dependencies=[
              # used by scrooge-generator in BUILD.tools:scrooge-gen
              jar(org='com.twitter', name='scrooge-core_2.9.2', rev='3.12.1').with_sources()
            ]
          )

jar_library(name='slf4j-api',
            dependencies=[
              jar(org='org.slf4j', name='slf4j-api', rev='1.6.1').with_sources()
            ]
)

jar_library(name='libthrift-0.5.0',
            dependencies=[
              jar(org='org.apache.thrift', name='libthrift', rev='0.5.0-1'),
            ]
           )

jar_library(name='thrift-0.5.0',
            dependencies=[
              pants(':commons-lang'),
              pants(':libthrift-0.5.0'),
              pants(':slf4j-api'),
            ]
           )

jar_library(name='thrift-0.5.0-finagle',
            dependencies=[
              pants(':thrift-0.5.0'),

              # finagle thrift extra deps
              pants(':finagle-core'),
              pants(':finagle-thrift'),
              pants(':util-core'),
            ]
           )

jar_library(name='thrift',
            dependencies=[ pants(':thrift-0.5.0') ])

# common rev for all com.twitter%util* artifacts
UTIL_REV = '6.8.1'

jar_library(name='util-core',
            dependencies=[
		    jar(org='com.twitter', name='util-core_2.9.2', rev=UTIL_REV).with_sources() ])


###############
# Test support
#

jar_library(name='easymock',
            dependencies=[
              jar(org='org.easymock', name='easymock', rev='3.2').with_sources(),
              # Class extension is needed to support the old version of easymockclassextension that
              # is not dependend on by the easymock dependency
              jar(org='org.easymock', name='easymockclassextension', rev='3.2').with_sources(),
            ]
           )

jar_library(name='mockito',
            dependencies=[
              jar(org='org.mockito', name='mockito-all', rev='1.9.0').with_sources()
            ]
           )

jar_library(name='hamcrest-core',
            dependencies=[ jar(org='org.hamcrest', name='hamcrest-core', rev='1.3') ])

jar_library(name='junit',
            dependencies=[
              jar(org='junit', name='junit-dep', rev='4.11').with_sources(),
              pants(':hamcrest-core')
            ]
           )

jar_library(name='specs_2.9',
            dependencies=[
              jar(org='org.scala-tools.testing', name='specs_2.9.3', rev='1.6.9')
            ]
           )

jar_library(name='specs', dependencies=[ pants(':specs_2.9') ])
