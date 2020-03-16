# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='lesser-of-two',
  main='org.pantsbuild.testproject.phrases.LesserOfTwo',
  sources=['LesserOfTwo.java'],
)

jvm_binary(name='once-upon-a-time',
  main='org.pantsbuild.testproject.phrases.OnceUponATime',
  sources=['OnceUponATime.java'],
)

jvm_binary(name='ten-thousand',
  main='org.pantsbuild.testproject.phrases.TenThousand',
  sources=['TenThousand.java'],
)

jvm_binary(name='there-was-a-duck',
  main='org.pantsbuild.testproject.phrases.ThereWasADuck',
  sources=['ThereWasADuck.java'],
  dependencies=[
    ':with-her-trusty-companion',
  ]
)

java_library(name='with-her-trusty-companion',
  sources=['TrustyCompanion.java'],
)
