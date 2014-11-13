# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
 # Licensed under the Apache License, Version 2.0 (see LICENSE).

# Redirect the protobuf dependency through a target() declaration
target(name='indirectprotodep',
  dependencies = [
    ':redirect',
  ],
)

java_protobuf_library(name='redirect',
  sources = globs('*.proto'),
)
