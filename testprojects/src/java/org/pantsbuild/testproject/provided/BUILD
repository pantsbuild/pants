# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='a',
  sources=['suba/A.java'],
)

java_library(name='b',
  sources=['subb/B.java'],
  dependencies=[
    provided(':a'),
  ],
)

java_library(name='c',
  sources=['subc/C.java'],
  dependencies=[
    provided(':b'),
  ],
)

jvm_binary(name='a-bin',
  main='org.pantsbuild.testproject.provided.suba.A',
  dependencies=[':a'],
)

jvm_binary(name='b-bin',
  main='org.pantsbuild.testproject.provided.subb.B',
  dependencies=[':b'],
)

jvm_binary(name='c-bin',
  main='org.pantsbuild.testproject.provided.subc.C',
  dependencies=[':c'],
)

jvm_binary(name='c-with-direct-dep',
  source='subc/C.java',
  main='org.pantsbuild.testproject.provided.subc.C',
  dependencies=[
    ':a',
    provided(':b'),
  ],
)


target(name='trans-1', dependencies=[':a'])
target(name='trans-2', dependencies=[':trans-1'])
target(name='trans-3', dependencies=[':trans-2'])
target(name='trans-4', dependencies=[':trans-3'])

jvm_binary(name='c-with-transitive-dep',
  source='subc/C.java',
  main='org.pantsbuild.testproject.provided.subc.C',
  dependencies=[
    ':trans-1',
    ':b',
  ],
)
