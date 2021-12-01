# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":java_resources"])
resources(name="java_resources", sources=["*.java", "java_parser.lockfile"])
python_tests(name="tests", timeout=240)

#
# Targets for developing on the Java parser outside of engine rules.
#

java_sources(
    name="java_parser",
    compatible_resolves=["java_parser"],
    dependencies=[
        # Update in concert with `java_parser_artifact_requirements`.
        # TODO: Move these definitions to thirdparty, and add to the thirdparty mapping to
        # enable inference.
        ":com.github.javaparser_javaparser-symbol-solver-core",
        ":com.fasterxml.jackson.core_jackson-databind",
        ":com.fasterxml.jackson.datatype_jackson-datatype-jdk8",
    ],
)

jvm_artifact(
    name="com.github.javaparser_javaparser-symbol-solver-core",
    group="com.github.javaparser",
    artifact="javaparser-symbol-solver-core",
    version="3.23.0",
)

jvm_artifact(
    name="com.fasterxml.jackson.core_jackson-databind",
    group="com.fasterxml.jackson.core",
    artifact="jackson-databind",
    version="2.12.4",
)

jvm_artifact(
    name="com.fasterxml.jackson.datatype_jackson-datatype-jdk8",
    group="com.fasterxml.jackson.datatype",
    artifact="jackson-datatype-jdk8",
    version="2.12.4",
)
