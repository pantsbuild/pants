# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
  sources = ['Manifest.java'],
  name = 'manifest-with-source',
  main = 'org.pantsbuild.testproject.manifest.Manifest',
  manifest_entries = {
    'Implementation-Version' :  '1.2.3',
  },
)

jvm_binary(
  name = 'manifest-no-source',
  main = 'org.pantsbuild.testproject.manifest.Manifest',
  manifest_entries = {
    'Implementation-Version' :  '4.5.6',
  },
  dependencies = [
    ':manifest-lib',
  ],
)

jvm_binary(
  name = 'manifest-with-agent',
  main = 'org.pantsbuild.testproject.manifest.Manifest',
  manifest_entries = {
    'Implementation-Version' :  '4.5.6',
  },
  dependencies = [':agent'],
)

java_library(
  name = 'manifest-lib',
  sources = ['Manifest.java'],
)

jvm_app(
  name = 'manifest-app',
  dependencies = [
    ':manifest-no-source',
  ]
)

java_agent(
  name = 'agent',
  agent_class = 'org.pantsbuild.testproject.manifest.Agent',
  sources = ['Agent.java'],
)
