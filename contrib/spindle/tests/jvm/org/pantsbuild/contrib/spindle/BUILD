# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(
  name = 'spindle',
  sources = globs('*.scala'),
  dependencies = [
    'contrib/spindle/3rdparty:rogue',
    'contrib/spindle/tests/thrift/org/pantsbuild/contrib/spindle:tvlisting',
    '3rdparty:junit',
  ],
)