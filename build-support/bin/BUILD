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
    overrides={"reversion_test.py": {"timeout": 90, "dependencies": ["3rdparty/python#pex"]}},
)

pex_binaries(
    execution_mode="venv",
    entry_points=[
        "cache_comparison.py",
        "changelog.py",
        "check_banned_imports.py",
        "check_inits.py",
        "contributors.py",
        "deploy_to_s3.py",
        "_generate_all_lockfiles_helper.py",
        "generate_docs.py",
        "generate_github_workflows.py",
        "generate_user_list.py",
        "_release_helper.py",
        "reversion.py",
    ],
)
