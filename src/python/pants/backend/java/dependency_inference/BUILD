# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":java_src"])
python_tests(name="tests", timeout=240)

resources(name="java_src", sources=["*.java"])

#
# Targets for developing on the Java parser outside of engine rules.
#

java_sources(
    name="javaparser",
    compatible_resolves=[
      "pants_java_parser",
    ],
    dependencies=[
        ":javaparser_lockfile",
        ":com.github.javaparser_javaparser-symbol-solver-core",
        ":com.fasterxml.jackson.core_jackson-databind",
    ],
)

jvm_artifact(
    name="com.github.javaparser_javaparser-symbol-solver-core",
    group="com.github.javaparser",
    artifact="javaparser-symbol-solver-core",
    version="3.23.0",
)

jvm_artifact(
  name = "com.fasterxml.jackson.core_jackson-databind",
  group = "com.fasterxml.jackson.core",
  artifact = "jackson-databind",
  version = "2.12.4",
)

coursier_lockfile(name="javaparser_lockfile", source="coursier_resolve.lockfile")
