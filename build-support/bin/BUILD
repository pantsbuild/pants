# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resources(name="docs_templates", sources=["docs_templates/*.mustache"])
resources(name="user_list_templates", sources=["user_list_templates/*.mustache"])

shell_sources(name="sh_scripts")

python_sources(
    name="py_scripts",
    overrides={
        "generate_docs.py": {"dependencies": [":docs_templates"]},
        "generate_user_list.py": {"dependencies": [":user_list_templates"]},
    },
)

python_tests(
    name="py_tests",
    overrides={
        "generate_json_schema_test.py": {
            "dependencies": [
                "build-support/bin/json_schema_testdata:json_schema_samples",
                "3rdparty/python#types-setuptools",
            ]
        },
    },
)

pex_binary(
    name="terraform_tool_versions",
    entry_point="terraform_tool_versions.py",
)
