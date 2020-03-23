# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This BUILD file contains several targets with scala libraries that can be compiled in parallel.

scala_library(
  name='simple_greeting',
  sources=['simple_greeting.scala'],
)

scala_library(
  name='greeting_by_name',
  sources=['greeting_by_name.scala'],
)

scala_library(
  name='greeting_everybody',
  sources=['greeting_everybody.scala'],
)
scala_library(
  name='greet_json',
  dependencies=[
    'examples/src/scala/org/pantsbuild/example/several_scala_targets/node:names_to_greet',
  ],
  sources=['GreetingJsonNames.scala'],
)

jvm_binary(
  name="greet_binary",
  dependencies=[
    'examples/src/scala/org/pantsbuild/example/several_scala_targets:greet_json',
  ],
  main='org.pantsbuild.example.several_scala_targets.greet_json_names.GreetingJsonNames',
)
