# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    overrides={
        "subsystem.py": {"dependencies": [":lockfiles"]},
    },
)

# Bundled lockfiles for the `openapi-format` NodeJSToolBase subsystem (one per package manager).
# To regenerate:
#   ./pants run build-support/bin/generate_builtin_lockfiles.py -- openapi-format
# Or for all NodeJS tools at once: `... -- --all-nodejs`.
resources(
    name="lockfiles",
    sources=["*.package-lock.json", "*.yarn.lock", "*.pnpm-lock.yaml"],
)
python_tests(name="tests")
