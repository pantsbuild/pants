# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
  name = 'aliases_directory',
  sources = rglobs('aliases/*'),
)

files(
  name = 'cycle1_directory',
  sources = rglobs('cycle1/*'),
)

files(
  name = 'cycle2_directory',
  sources = rglobs('cycle2/*'),
)

files(
  name = 'intransitive_directory',
  sources = rglobs('intransitive/*'),
)

files(
  name = 'phrases_directory',
  sources = rglobs('phrases/*'),
)

files(
  name = 'printversion_directory',
  sources = rglobs('printversion/*'),
)

files(
  name = 'runtime_directory',
  sources = rglobs('runtime/*'),
)

files(
  name = 'unicode_directory',
  sources = rglobs('unicode/*'),
  dependencies = [
    'testprojects/src/scala/org/pantsbuild/testproject:unicode_directory',
  ],
)
