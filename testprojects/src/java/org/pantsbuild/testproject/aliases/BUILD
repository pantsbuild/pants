# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This is here as part of an integration test for the `alias()` syntax.

alias('convenient', ':inconveniently-named-binary')

jvm_binary(name='inconveniently-named-binary',
  main='org.pantsbuild.testproject.aliases.AliasedBinaryMain',
  dependencies=[
    ':main',
  ],
)

java_library(name='main',
  sources=[
    'AliasedBinaryMain.java',
  ],
)

java_library(name='intransitive-dependency',
  sources=[
    'IntransitiveDependency.java',
  ],
)

# Using a normal target() here instead of an alias fails, because its dependencies are unable
# to see the intransitive dep.
alias('indirection', intransitive(':intransitive-dependency'))

java_library(name='use-intransitive-dependency',
  sources=[
    'UseIntransitiveDependency.java',
  ],
  dependencies=[
    ':indirection',
  ],
)

jvm_binary(name='run-use-intransitive',
  main='org.pantsbuild.testproject.aliases.UseIntransitiveDependency',
  dependencies=[
    ':use-intransitive-dependency',
  ],
)
