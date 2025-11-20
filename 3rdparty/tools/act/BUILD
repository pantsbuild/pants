# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This contains all the plumbing in order to get https://github.com/nektos/act working in a sandbox
# and in `run`.
# To run `act`, use `pants run 3rdparty/tools/act -- --version` (or whatever args you want).

file(
    name="downloaded-act",
    source=per_platform(
        macos_x86_64=http_source(
            url="https://github.com/nektos/act/releases/download/v0.2.82/act_Darwin_x86_64.tar.gz",
            len=8007436,
            sha256="cdfcc8b15c55f936287626e13c8b31fa576257133b6595642cda9b32fa3b17b6",
            filename="act.tar.gz",
        ),
        macos_arm64=http_source(
            url="https://github.com/nektos/act/releases/download/v0.2.82/act_Darwin_arm64.tar.gz",
            len=7523767,
            sha256="c4cc7d34f497eb15f51f8f6e1d25571e18b4909ceceb40933f4a26a8e7293cfb",
            filename="act.tar.gz",
        ),
        linux_x86_64=http_source(
            url="https://github.com/nektos/act/releases/download/v0.2.82/act_Linux_x86_64.tar.gz",
            len=7874545,
            sha256="76645c0bbe4bb69a8f0ba3caefa681b2f4c04babd4679c67861af9a276a3561f",
            filename="act.tar.gz",
        ),
        linux_arm64=http_source(
            url="https://github.com/nektos/act/releases/download/v0.2.82/act_Linux_arm64.tar.gz",
            len=7235851,
            sha256="ebf375e700f6f2c139fe3c5508af2ec85032a75e7d29f6a388a58c0fab76e951",
            filename="act.tar.gz",
        ),
    ),
)

shell_command(
    name="extracted-act",
    command="tar -xf act.tar.gz",
    tools=["tar", "gzip"],
    execution_dependencies=[":downloaded-act"],
    output_files=["act"],
)

file(
    name=".actrc",
    source=".actrc",
)

relocated_files(
    name="act-at-root",
    files_targets=[":extracted-act", ":.actrc"],
    src=f"{build_file_dir()}",
    dest="",
)

run_shell_command(
    name="act",
    # NB: Use XDG_CONFIG_DIRS so the .actrc gets loaded from the sandbox
    command="XDG_CONFIG_DIRS=${CHROOT}:$XDG_CONFIG_DIRS {chroot}/act $@",
    workdir="/",
    execution_dependencies=[":act-at-root"],
)
