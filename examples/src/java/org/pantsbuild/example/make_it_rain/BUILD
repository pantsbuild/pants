# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
    sources = ["MakeItRain.java"],
    description = """
This target is useful to be able to compile the referenced thrift targets,
or to publish them. Try running the following to test it out:
$ yes | ./pants publish.jar --local=/tmp/m2 --no-dryrun \\
                            examples/src/java/org/pantsbuild/example/make_it_rain
""",
    provides = artifact(
        name = "make-it-rain",
        org = "org.pantsbuild.example",
        repo = public,
    ),
    dependencies = [
        "3rdparty:thrift-0.9.2",
        "examples/src/thrift/org/pantsbuild/example/distance:distance-java",
        "examples/src/thrift/org/pantsbuild/example/precipitation:precipitation-java",
    ],
)
