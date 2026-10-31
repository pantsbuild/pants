# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfiles"])

# The *.package-lock.json / *.yarn.lock / *.pnpm-lock.yaml entries are bundled lockfiles for the
# `redocly` NodeJSToolBase subsystem. To regenerate:
#   ./pants run build-support/bin/generate_builtin_lockfiles.py -- redocly
# Or for all NodeJS tools at once: `... -- --all-nodejs`.
resources(
    name="lockfiles",
    sources=["*.lockfile.txt", "*.package-lock.json", "*.yarn.lock", "*.pnpm-lock.yaml"],
)
