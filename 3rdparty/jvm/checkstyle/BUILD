# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
  name='checkstyle',
  jars = [
    jar(org='com.puppycrawl.tools', name='checkstyle', rev='5.5')
      .exclude(org='com.google.collections', name='google-collections')
      .with_sources(),
  ],
  dependencies = [
    # Needs this as the replacement for the excluded google-collections.
    '3rdparty/jvm/guava',
  ],
)
