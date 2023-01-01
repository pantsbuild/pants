# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":java_resources"])
resources(name="java_resources", sources=["*.java", "strip_jar.lock"])
python_tests(name="tests", timeout=240)

# Targets for developing on the strip jar outside of engine rules.
java_sources(
    name="strip_jar_java",
    resolve="strip_jar_dev",
)

jvm_artifact(
    name="reproducible-builds-jvm-stripper",
    group="io.github.zlika",
    artifact="reproducible-build-maven-plugin",
    version="0.16",
    resolve="strip_jar_dev",
    packages=["io.github.zlika.reproducible.**"],
)
