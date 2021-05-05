# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

shell_library(name="sh_scripts")

python_library(name="py_scripts")
python_tests(name="py_tests", timeout=90)  # reversion_test.py times out occasionally.
resources(name="docs_templates", sources=["docs_templates/*.mustache"])

pex_binary(name="changelog", entry_point="changelog.py")
pex_binary(name="check_banned_imports", entry_point="check_banned_imports.py")
pex_binary(name="check_inits", entry_point="check_inits.py")
pex_binary(name="deploy_to_s3", entry_point="deploy_to_s3.py")
pex_binary(name="generate_github_workflows", entry_point="generate_github_workflows.py")
pex_binary(name="generate_docs", entry_point="generate_docs.py", dependencies=[":docs_templates"])
pex_binary(name="reversion", entry_point="reversion.py")

# TODO: Get rid of this weirdness once we stop using sys.executable in the script, along with the `venv` module, and
#  instead invoke Pants to handle interpreter selection.
pex_binary(name="release_37", entry_point="release.py", interpreter_constraints=['==3.7.*'])
pex_binary(name="release_38", entry_point="release.py", interpreter_constraints=['==3.8.*'])
pex_binary(name="release_39", entry_point="release.py", interpreter_constraints=['==3.9.*'])
