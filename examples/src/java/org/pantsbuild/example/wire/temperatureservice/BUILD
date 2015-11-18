# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='temperatureservice',
  basename='wire-temperature-example',
  dependencies=[
    'examples/src/wire/org/pantsbuild/example/temperature',
  ],
  source='WireTemperatureExample.java',
  main='org.pantsbuild.example.pants.temperatureservice.WireTemperatureExample',
  # TODO: The 'wire' library is not actually defined in a BUILD file: it comes in
  # via the tool classpath of the sythetic target.
  strict_deps=False,
)
