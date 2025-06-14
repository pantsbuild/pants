# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# Root workspace - includes all TypeScript sources as transitive dependencies
# This is a temporary hack until dependency inference is working
package_json(dependencies=[
    ":jest_config", 
    ":jest_setup", 
    ":tsconfig",
    # Include all package targets to get their tsconfig.json files
    "./common-types:common-types",
    "./main-app:main-app",
    "./shared-components:shared-components", 
    "./shared-utils:shared-utils",
    # Include all TypeScript source targets to make them available during installation
    "./common-types/src:src",
    "./main-app/src:ts_sources",
    "./main-app/src:tsx_sources", 
    "./shared-components/src:ts_sources",
    "./shared-components/src:tsx_sources",
    "./shared-utils/src:sources",
])

file(name="pnpm_workspace", source="pnpm-workspace.yaml")
file(name="jest_config", source="jest.config.js")
file(name="jest_setup", source="jest-setup.ts")
file(name="tsconfig", source="tsconfig.json")
