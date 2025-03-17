# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


shell_sources(name="sh_scripts")

python_sources(
    name="py_scripts",
    overrides={
        "external_tool_upgrade.py": {
            "resolve": "external-tool-upgrade",
        }
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
        "external_tool_upgrade_test.py": {
            "resolve": "external-tool-upgrade",
        }
    },
)

pex_binary(
    name="terraform_tool_versions",
    entry_point="terraform_tool_versions.py",
)

pex_binary(
    name="external-tool-upgrade",
    entry_point="external_tool_upgrade.py",
    execution_mode="venv",
    resolve="external-tool-upgrade",
)
