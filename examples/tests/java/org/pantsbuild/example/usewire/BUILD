# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Tests functionality of wire generating java code.

junit_tests(name='usewire',
  sources=['UseWireTest.java',],
  dependencies=[
    '3rdparty:junit',
    'examples/src/wire/org/pantsbuild/example/temperature',
  ],
  # TODO: The 'wire' library is not actually defined in a BUILD file: it comes in
  # via the tool classpath of the sythetic target.
  strict_deps=False,
)
