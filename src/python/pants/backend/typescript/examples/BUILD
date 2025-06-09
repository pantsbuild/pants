# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# Root workspace - minimal package.json declaration
package_json(dependencies=[":jest_config", ":jest_setup", ":tsconfig"])

file(name="pnpm_workspace", source="pnpm-workspace.yaml")
file(name="jest_config", source="jest.config.js")
file(name="jest_setup", source="jest-setup.ts")
file(name="tsconfig", source="tsconfig.json")
