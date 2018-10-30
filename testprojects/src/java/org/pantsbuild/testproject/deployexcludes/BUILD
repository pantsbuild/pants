# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

def jvm_excludes_binary(name, excludes=True):
  deploy_excludes = [exclude(org='com.google.guava', name='guava')] if excludes else []
  jvm_binary(
    name=name,
    main='org.pantsbuild.testproject.deployexcludes.DeployExcludesMain',
    dependencies=[
      ':lib',
    ],
    deploy_excludes=deploy_excludes,
  )

jvm_excludes_binary('deployexcludes', excludes=True)
jvm_excludes_binary('nodeployexcludes', excludes=False)

java_library(
  name='lib',
  sources=['DeployExcludesMain.java'],
  dependencies=[
    '3rdparty:guava',
  ],
)
