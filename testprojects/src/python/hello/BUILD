# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

resources(name="resource", sources=["dist_resource.txt"])

python_distribution(
    name="hello-dist",
    dependencies=["testprojects/src/python/hello/greet", ":resource"],
    provides=setup_py(
        name="hello-dist",
        version="0.0.1",
        zip_safe=True,
    ),
)
