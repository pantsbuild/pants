# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Targets for running the GitHub CLI (or `gh`): https://cli.github.com/
# Use `pants run 3rdparty/tools/gh -- <args>`

file(
    name="downloaded-gh",
    source=per_platform(
        macos_x86_64=http_source(
            url="https://github.com/cli/cli/releases/download/v2.32.0/gh_2.32.0_macOS_amd64.zip",
            len=10957234,
            sha256="e6dd7cb61338c6aab27dfc744bf74817f26a938e505a8e817316513ebf02eb57",
            filename="gh.archive",
        ),
        macos_arm64=http_source(
            url="https://github.com/cli/cli/releases/download/v2.32.0/gh_2.32.0_macOS_arm64.zip",
            len=10318229,
            sha256="6df08a326a4c00e6d33f49c458402c8a3921fd71a2f3187ce77ddb6c452d73f0",
            filename="gh.archive",
        ),
        linux_x86_64=http_source(
            url="https://github.com/cli/cli/releases/download/v2.32.0/gh_2.32.0_linux_amd64.tar.gz",
            len=10315710,
            sha256="2e306f118a46764bc1763bacc52e7b18eeca5aa6fd59d2b5fd260f0ef3cd87ae",
            filename="gh.archive",
        ),
        linux_arm64=http_source(
            url="https://github.com/cli/cli/releases/download/v2.32.0/gh_2.32.0_linux_arm64.tar.gz",
            len=9410807,
            sha256="9eff1eb5d13a3fa858859bd2995077f8987a89d352548a3c116af0536f49afc0",
            filename="gh.archive",
        ),
    ),
)

shell_source(
    name="extract.sh",
    source="extract.sh",
)

shell_command(
    name="extracted-gh",
    command="./extract.sh",
    tools=["tar", "gzip", "zip", "mv", "mkdir", "bash"],
    execution_dependencies=[":downloaded-gh", ":extract.sh"],
    output_directories=["gh"],
)

relocated_files(
    name="relocated-gh",
    files_targets=[":extracted-gh"],
    src="3rdparty/tools/gh/gh",
    dest="3rdparty/tools/gh",
)

run_shell_command(
    name="gh",
    command="{chroot}/3rdparty/tools/gh/bin/gh",
    execution_dependencies=[":relocated-gh"],
)
