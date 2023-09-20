# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

file(
    name="rustup-init",
    source=per_platform(
        linux_arm64=http_source(
            url="https://static.rust-lang.org/rustup/archive/1.26.0/aarch64-unknown-linux-gnu/rustup-init",
            len=14131368,
            sha256="673e336c81c65e6b16dcdede33f4cc9ed0f08bde1dbe7a935f113605292dc800",
        ),
        linux_x86_64=http_source(
            url="https://static.rust-lang.org/rustup/archive/1.26.0/x86_64-unknown-linux-gnu/rustup-init",
            len=14293176,
            sha256="0b2f6c8f85a3d02fde2efc0ced4657869d73fccfce59defb4e8d29233116e6db",
        ),
        macos_arm64=http_source(
            url="https://static.rust-lang.org/rustup/archive/1.26.0/aarch64-apple-darwin/rustup-init",
            len=8000713,
            sha256="ed299a8fe762dc28161a99a03cf62836977524ad557ad70e13882d2f375d3983",
        ),
        macos_x86_64=http_source(
            url="https://static.rust-lang.org/rustup/archive/1.26.0/x86_64-apple-darwin/rustup-init",
            len=8670640,
            sha256="f6d1a9fac1a0d0802d87c254f02369a79973bc8c55aa0016d34af4fcdbd67822",
        ),
    ),
)

shell_command(
    name="cargo-shim",
    command="""
        chmod +x rustup-init
        ./rustup-init --no-modify-path --no-update-default-toolchain --profile minimal --default-toolchain none -y
    """,
    extra_env_vars=["RUSTUP_HOME=dummy", "CARGO_HOME=shims"],
    tools=["chmod"],
    execution_dependencies=[":rustup-init"],
    output_directories=["shims/bin"],
)

shell_command(
    name="cargo",
    command="""
        mv ../../../src/rust/engine/rust-toolchain rust-toolchain
        ./shims/bin/rustup set profile minimal
        ./shims/bin/cargo version
        mv toolchains/* cargo
    """,
    extra_env_vars=["RUSTUP_HOME=."],
    tools=["mv"],
    execution_dependencies=[
        ":cargo-shim",
        "src/rust/engine:rust-toolchain",
    ],
    output_directories=["cargo"],
    timeout=600,
)
