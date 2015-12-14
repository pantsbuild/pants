# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='deployexcludes',
  main='org.pantsbuild.testproject.deployexcludes.DeployExcludesMain',
  dependencies=[
    ':lib',
  ],
  deploy_excludes=[
    exclude(org='com.google.guava', name='guava'),
  ],
)

java_library(name='lib',
  sources=['DeployExcludesMain.java'],
  dependencies=[
    '3rdparty:guava',
  ],
)
