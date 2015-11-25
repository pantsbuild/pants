# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='element',
  basename='wire-element-example',
  dependencies=[
    'examples/src/wire/org/pantsbuild/example/element',
  ],
  source='WireElementExample.java',
  main='org.pantsbuild.example.wire.element.WireElementExample',
  # TODO: The 'wire' library is not actually defined in a BUILD file: it comes in
  # via the tool classpath of the sythetic target.
  strict_deps=False,
)

