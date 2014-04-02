# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

ORG = 'com.sun.jersey'
REV = '1.12'

jar_library(name='jersey-client',
            dependencies=[jar(org=ORG, name='jersey-client', rev=REV).with_sources()])

jar_library(name='jersey-core',
            dependencies=[jar(org=ORG, name='jersey-core', rev=REV).with_sources()])

jar_library(name='jersey-server',
            dependencies=[jar(org=ORG, name='jersey-server', rev=REV).with_sources()])

jar_library(name='jersey-servlet',
            dependencies=[jar(org=ORG, name='jersey-servlet', rev=REV).with_sources()])

jar_library(name='jersey-guice',
            dependencies=[jar(org='com.sun.jersey.contribs', name='jersey-guice', rev=REV).with_sources()])
