# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='lib',
  dependencies=[
    ':all-files',
  ],
)

resources(name='all-files',
  sources=rglobs('*', exclude=[globs('BUILD*')]),
)

resources(name='java-files',
  sources=rglobs('*/*.java'),
)

resources(name='scala-files',
  sources=rglobs('*/*.scala'),
)

resources(name='text-files',
  sources=rglobs('*/*.txt'),
)
