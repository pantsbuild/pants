# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
#  Example of annotation_processor() target

annotation_processor(
    sources = ["ExampleProcessor.java"],
    processors = ["org.pantsbuild.example.annotation.processor.ExampleProcessor"],
    scope = "forced",
    dependencies = [
        "3rdparty:guava",
        "examples/src/java/org/pantsbuild/example/annotation/example",
    ],
)
