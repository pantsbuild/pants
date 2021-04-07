# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# We use this to establish the build root, rather than `./pants`, because we cannot safely use the
# latter as the sentinel filename per https://github.com/pantsbuild/pants/pull/8105.
files(name='build_root', sources=["BUILD_ROOT"])

files(name='gitignore', sources=['.gitignore'])
files(name='pants_toml', sources=['pants.toml'])
files(name='pyproject', sources=['pyproject.toml'])

shell_library(
    name="pants",
    sources=["pants"],
    dependencies=["build-support/common.sh", "build-support/pants_venv", "build-support/bin/rust/bootstrap_code.sh"],
)
shell_library(name="cargo", sources=["cargo"], dependencies=["build-support/common.sh"])
