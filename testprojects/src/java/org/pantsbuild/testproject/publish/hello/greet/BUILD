# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
    provides = artifact(
        name = "hello-greet",
        org = "org.pantsbuild.testproject.publish",
        publication_metadata = ossrh(
            description = "A simple greeter.",
            developers = [
                developer(
                    user_id = "jane",
                ),
                developer(
                    name = "George Jones",
                ),
                developer(
                    email = "charlie@example.com",
                    roles = [
                        "greenman",
                        "wildcard",
                    ],
                ),
                developer(
                    name = "Jack Spratt",
                    email = "jack.spratt@example.com",
                ),
            ],
            licenses = [
                license(
                    name = "MIT License",
                    url = "http://www.opensource.org/licenses/mit-license.php",
                ),
                license(
                    name = "To Ill",
                    comments = "Covers legacy releases.",
                    url = "http://brassmonkey.example.org/",
                ),
            ],
            scm = github(
                repo = "pants",
                user = "pantsbuild",
            ),
            url = "https://github.com/pantsbuild/pants/tree/master/" +
                  "testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet",
        ),
        repo = testing,
    ),
    dependencies = [
        ":readme",
    ],
)

resources(
    name = "readme",
    sources = globs("*.txt"),
)
