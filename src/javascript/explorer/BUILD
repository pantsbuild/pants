# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
    sources=[
        "package.json",
        "public/**",
        "src/**",
        "tsconfig.json",
        "tsconfig.paths.json",
        "yarn.lock",
    ],
)

experimental_shell_command(
    name="node-dependencies",
    command="yarn install",
    tools=[
        "node",
        "yarn",
    ],
    outputs=["node_modules/"],
    dependencies=[":explorer"],
)

experimental_shell_command(
    name="dist",
    command="yarn build",
    tools=[
        "node",
        "yarn",
    ],
    outputs=["dist/"],
    dependencies=[":explorer", ":node-dependencies"]
)

# The `dist` shell command fails, currently. Work-around is to build manually for now.
files(
    name="dist-files",
    sources=["dist/**"],
)
