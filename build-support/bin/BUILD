# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()
python_tests(name="tests", timeout=90)  # reversion_test.py times out occasionally.

files(name="bash_scripts", sources=["*.sh"])
resources(name="docs_templates", sources=["docs_templates/*.mustache"])

pex_binary(name="bootstrap_and_deploy_ci_pants_pex", entry_point="bootstrap_and_deploy_ci_pants_pex.py")
pex_binary(name="changelog", entry_point="changelog.py")
pex_binary(name="check_banned_imports", entry_point="check_banned_imports.py")
pex_binary(name="check_inits", entry_point="check_inits.py")
pex_binary(name="ci", entry_point="ci.py")
pex_binary(name="deploy_to_s3", entry_point="deploy_to_s3.py")
pex_binary(name="generate_travis_yml", entry_point="generate_travis_yml.py")
pex_binary(name="generate_docs", entry_point="generate_docs.py", dependencies=[":docs_templates"])
pex_binary(name="reversion", entry_point="reversion.py",)
pex_binary(name="shellcheck", entry_point="shellcheck.py")
pex_binary(name="packages", entry_point="packages.py")  # TODO: rename to `release.py` after removing `release.sh`.
