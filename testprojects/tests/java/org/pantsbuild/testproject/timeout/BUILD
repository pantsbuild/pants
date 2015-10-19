# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='passing_target',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:junit',
  ],
  timeout=3
)

junit_tests(name='failing_target',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:junit',
  ],
  timeout=1
)
