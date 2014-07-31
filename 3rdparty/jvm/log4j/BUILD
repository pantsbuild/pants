# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
  name = 'log4j',
  jars = [
    jar(org='log4j', name='log4j', rev='1.2.15')
      .exclude(org='jline', name='jline')
      .exclude(org='javax.jms', name='jms')
      .exclude(org='com.sun.jdmk', name='jmxtools')
      .exclude(org='com.sun.jmx', name='jmxri')
      .with_sources()
  ],
)
