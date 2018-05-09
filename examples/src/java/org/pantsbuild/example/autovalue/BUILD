# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
  main = 'org.pantsbuild.example.autovalue.AutoValueMain',
  dependencies = [
    ':autovalue-lib',
  ],
)

# DOCSTART: This target is included in documentation.
java_library(name='autovalue-lib',
  dependencies = [
    '3rdparty/jvm/com/google/auto/value',
  ],
)
# DOCEND
