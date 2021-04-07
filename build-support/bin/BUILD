# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

shell_library(
    name="sh_scripts",
    dependencies=["build-support/common.sh", "build-support/pants_venv", "build-support/bin/rust/bootstrap_code.sh"],
)

python_library(name="py_scripts")
python_tests(name="py_tests", timeout=90)  # reversion_test.py times out occasionally.
resources(name="docs_templates", sources=["docs_templates/*.mustache"])

pex_binary(name="changelog", entry_point="changelog.py")
pex_binary(name="check_banned_imports", entry_point="check_banned_imports.py")
pex_binary(name="check_inits", entry_point="check_inits.py")
pex_binary(name="deploy_to_s3", entry_point="deploy_to_s3.py")
pex_binary(name="generate_github_workflows", entry_point="generate_github_workflows.py")
pex_binary(name="generate_docs", entry_point="generate_docs.py", dependencies=[":docs_templates"])
pex_binary(name="reversion", entry_point="reversion.py",)
pex_binary(name="packages", entry_point="packages.py")  # TODO: rename to `release.py` after removing `release.sh`.
