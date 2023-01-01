# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

docker_image(
    name="test-example",
    image_tags=["1.2.5"],
    source="Dockerfile.example",
)

docker_image(
    name="test-example-synth",
    image_tags=["1.2.5"],
    instructions=[
        "FROM python:3.7",
        'ENTRYPOINT ["/hello"]',
        'CMD ["synthetic!"]',
        "COPY testprojects.src.python.hello.main/main.pex /hello",
    ],
)
