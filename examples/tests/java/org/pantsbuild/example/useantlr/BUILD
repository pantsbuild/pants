# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(name='useantlr',
  dependencies=[
    ':antlr3_test',
    ':antlr4_test',
  ],
)

junit_tests(name='antlr3_test',
  sources=['Antlr3Test.java',],
  dependencies=[
    '3rdparty:junit',
    'examples/src/java/org/pantsbuild/example/antlr3',
  ],
)

junit_tests(name='antlr4_test',
  sources=['Antlr4Test.java',],
  dependencies=[
    '3rdparty:junit',
    'examples/src/java/org/pantsbuild/example/antlr4',
  ],
)
