# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='cucumber',
  sources=globs('*.java'),
  dependencies = [
    # This dependency is only used for an annotation, which zinc's analysis will not report.
    scoped('3rdparty:cucumber-java', scope='forced'),
  ],
)
