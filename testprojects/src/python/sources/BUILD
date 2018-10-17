# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
  name='missing-sources',
)

python_library(
  dependencies=[
    ':text',
  ],
  sources=globs('*.py'),
)

resources(
  name='text',
  sources=globs('*.txt'),
)

resources(
  name='missing-globs',
  sources=globs('*.a'),
)

resources(
  name='missing-rglobs',
  sources=rglobs('*.a'),
)

resources(
  name='missing-zglobs',
  sources=zglobs('**/*.a'),
)

resources(
  name='missing-literal-files',
  sources=[
    'nonexistent_test_file.txt',
    'another_nonexistent_file.txt',
  ],
)

resources(
  name='some-missing-some-not',
  sources=globs('*.txt', '*.rs'),
)

resources(
  name='overlapping-globs',
  sources=globs('sources.txt', '*.txt'),
)
