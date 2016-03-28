# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='compile-fail',
  source='CompileReference.java',
  main='org.pantsbuild.testproject.runtime.CompileReference',
  dependencies=[
    scoped('3rdparty:gson', scope='runtime'),
  ],
)

jvm_binary(name='compile-pass',
  source='CompileReference.java',
  main='org.pantsbuild.testproject.runtime.CompileReference',
  dependencies=[
    scoped('3rdparty:gson', scope='compile'),
  ],
)

jvm_binary(name='runtime-fail',
  source='RuntimeReference.java',
  main='org.pantsbuild.testproject.runtime.RuntimeReference',
  dependencies=[
    scoped('3rdparty:gson', scope='compile'),
  ],

)

jvm_binary(name='runtime-pass',
  source='RuntimeReference.java',
  main='org.pantsbuild.testproject.runtime.RuntimeReference',
  dependencies=[
    scoped('3rdparty:gson', scope='runtime'),
  ],
)
