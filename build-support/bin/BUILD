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

python_requirement(
    name="chevron",
    requirements=["chevron==0.14.0"],
)

python_tests(name="py_tests", overrides={"reversion_test.py": {"timeout": 90}})

pex_binary(name="changelog", entry_point="changelog.py")
pex_binary(name="check_banned_imports", entry_point="check_banned_imports.py")
pex_binary(name="check_inits", entry_point="check_inits.py")
pex_binary(name="deploy_to_s3", entry_point="deploy_to_s3.py")
pex_binary(
    name="generate_all_lockfiles_helper",
    entry_point="_generate_all_lockfiles_helper.py",
    dependencies=[":chevron"],
)
pex_binary(name="generate_docs", entry_point="generate_docs.py")
pex_binary(name="generate_github_workflows", entry_point="generate_github_workflows.py")
pex_binary(name="generate_user_list", entry_point="generate_user_list.py")
pex_binary(name="release_helper", entry_point="_release_helper.py")
pex_binary(name="reversion", entry_point="reversion.py")
