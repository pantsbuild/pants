# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This contains all the plumbing in order to get https://github.com/nektos/act working in a sandbox
# and in `run`.
# To run `act`, use `pants run 3rdparty/tools/act -- --version` (or whatever args you want).

file(
    name="downloaded-act",
    source=per_platform(
        macos_x86_64=http_source(
            url="https://github.com/nektos/act/releases/download/v0.2.46/act_Darwin_x86_64.tar.gz",
            len=6289585,
            sha256="503bd4560afa3394fac87c404d4b34d1b422b8bb136b7f4ddaab27d08367700a",
            filename="act.tar.gz",
        ),
        macos_arm64=http_source(
            url="https://github.com/nektos/act/releases/download/v0.2.46/act_Darwin_arm64.tar.gz",
            len=6015670,
            sha256="6e5aae98192747d9430625cf0ac42e9fbcdbd9bc5e2558eb0297d0e2f9f2b2a8",
            filename="act.tar.gz",
        ),
        linux_x86_64=http_source(
            url="https://github.com/nektos/act/releases/download/v0.2.46/act_Linux_x86_64.tar.gz",
            len=6079499,
            sha256="19d5cdf534f892c1b62c32765c3982e2eb1334d66de4cc7e4a0e568cc0256f44",
            filename="act.tar.gz",
        ),
        linux_arm64=http_source(
            url="https://github.com/nektos/act/releases/download/v0.2.46/act_Linux_arm64.tar.gz",
            len=5544514,
            sha256="06418ca7430df409940812afe343c00118d7df889b11422232ff31a32a32b737",
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
