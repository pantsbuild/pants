# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

page(
  name = 'readme',
  source = 'README.md',
  links = [
    'examples/src/java/org/pantsbuild/example:readme',
  ],
)

files(
  name = 'fact_directory',
  sources = rglobs('fact/*'),
)

files(
  name = 'hello_directory',
  sources = rglobs('hello/*'),
  dependencies = [
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/resources/org/pantsbuild/example:hello_directory',
  ],
)

files(
  name = 'jvm_run_directory',
  sources = rglobs('jvm_run/*'),
  dependencies = [
    ':hello_directory',
  ],
)

files(
  name = 'scalac_directory',
  sources = rglobs('scalac/*'),
)

files(
  name = 'several_scala_targets_directory',
  sources = rglobs('several_scala_targets/*'),
)

files(
  name = 'styleissue_directory',
  sources = rglobs('styleissue/*'),
)
