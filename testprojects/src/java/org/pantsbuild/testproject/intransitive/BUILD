# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='intransitive',
  source='A.java',
  main='org.pantsbuild.testproject.intransitive.A',
  dependencies=[
    ':diamond',
    intransitive(':b'),
  ],
)

# This demonstrates (a) diamond dependencies don't cause problems, and (b) multiple intransitive()
# aliases pointing to the same target in the same BUILD file don't cause problems.
target(name='diamond',
  dependencies=[
    intransitive(':b'),
  ],
)

java_library(name='b',
  sources=['B.java'],
  dependencies=[
    intransitive(':c'),
  ],
)

java_library(name='c',
  sources=['C.java'],
)
