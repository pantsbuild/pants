# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    sources=["*.py", "!*_test.py", "!post_renderer_main.py", "!k8s_parser_main.py"],
    dependencies=[":post_renderer", ":k8s_parser"],
)

python_tests(name="tests")

# Post-Renderer

python_requirement(
    name="yamlpath",
    requirements=[
        "yamlpath>=3.7,<4",
        "ruamel.yaml>=0.15.96,!=0.17.0,!=0.17.1,!=0.17.2,!=0.17.5,<=0.17.21",
    ],
    resolve="helm-post-renderer",
)

python_sources(
    name="__post_renderer_main",
    sources=["post_renderer_main.py"],
    resolve="helm-post-renderer",
    skip_mypy=True,
)

resources(name="post_renderer", sources=["post_renderer.lock", "post_renderer_main.py"])

# Kubernetes manifest parser

python_requirement(name="k8s", requirements=["hikaru==0.11.0b"], resolve="helm-k8s-parser")

python_sources(
    name="__k8s_parser_main",
    sources=["k8s_parser_main.py"],
    resolve="helm-k8s-parser",
    skip_mypy=True,
)

resources(name="k8s_parser", sources=["k8s_parser.lock", "k8s_parser_main.py"])
