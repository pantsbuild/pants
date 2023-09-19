# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: TO get the links/hashes go to https://static.rust-lang.org/manifests.txt, then for the relevant
# TOML for the version, go to that URL.

file(
    name="compressed-cargo",
    source=per_platform(
        linux_arm64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/cargo-1.72.0-aarch64-unknown-linux-gnu.tar.gz",
            len=13144016,
            sha256="ae2414ed0e30340fa2994e1c4b4e809c2bb1a3c054de395540f5ec1aa1b35072",
            filename="cargo.tar.gz",
        ),
        linux_x86_64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/cargo-1.72.0-x86_64-unknown-linux-gnu.tar.gz",
            len=13011632,
            sha256="bdd0589277041b7e6375e2782f9ce197f454f735642f118acb3a2d8e422770a4",
            filename="cargo.tar.gz",
        ),
        macos_arm64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/cargo-1.72.0-aarch64-apple-darwin.tar.gz",
            len=9236959,
            sha256="fc5d3c2f618fd691b6d61e8f845648c2b4d4b0981fab4d5f563615fa4673bfa7",
            filename="cargo.tar.gz",
        ),
        macos_x86_64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/cargo-1.72.0-x86_64-apple-darwin.tar.gz",
            len=9880166,
            sha256="a16f7c17a24a57c5990b104271524c33320da0006446aabeaa25eb0e718dd450",
            filename="cargo.tar.gz",
        ),
    ),
)

file(
    name="compressed-rustc",
    source=per_platform(
        linux_arm64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/rustc-1.72.0-aarch64-unknown-linux-gnu.tar.gz",
            len=152371343,
            sha256="3a2d1a5b5b713615162dcaa6319b6ad65ab4b951f90557dfb1e5c54f2a64c4ee",
            filename="rustc.tar.gz",
        ),
        linux_x86_64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/rustc-1.72.0-x86_64-unknown-linux-gnu.tar.gz",
            len=119891076,
            sha256="f414557b12f2a7a61fabf152b4b9d6cb436ff15698e64a3111bca1a94be97a3e",
            filename="rustc.tar.gz",
        ),
        macos_arm64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/rustc-1.72.0-aarch64-apple-darwin.tar.gz",
            len=96788681,
            sha256="8314d30747d95e62345d46b682bf490fa1b397d194294fae917bf72a6eda9709",
            filename="rustc.tar.gz",
        ),
        macos_x86_64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/rustc-1.72.0-x86_64-apple-darwin.tar.gz",
            len=92090616,
            sha256="93d50e6d828214b6a97086a10193f5cbbf64e84f240196849e96b7ceef2d224a",
            filename="rustc.tar.gz",
        ),
    ),
)

file(
    name="compressed-rust-std",
    source=per_platform(
        linux_arm64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/rust-std-1.72.0-aarch64-unknown-linux-gnu.tar.gz",
            len=64875725,
            sha256="dd504733d3d8939b448ee93247d62d7fb09316b54c2f247b3c9f4709bf70784d",
            filename="rust-std.tar.gz",
        ),
        linux_x86_64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/rust-std-1.72.0-x86_64-unknown-linux-gnu.tar.gz",
            len=46275300,
            sha256="89f6f6ef25e7e754940c54cc0584bfdb83e1df75019d5aa126e3fa66c2921b15",
            filename="rust-std.tar.gz",
        ),
        macos_arm64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/rust-std-1.72.0-aarch64-apple-darwin.tar.gz",
            len=40654475,
            sha256="24d7a92bed5a1841933cb6a6ec12050c750c766c840460f45de843c1e164ea59",
            filename="rust-std.tar.gz",
        ),
        macos_x86_64=http_source(
            url="https://static.rust-lang.org/dist/2023-08-24/rust-std-1.72.0-x86_64-apple-darwin.tar.gz",
            len=43014050,
            sha256="1d408dd46105b6f5256a00f4b116a8e385089a9647b7189497daf1a2dd728a19",
            filename="rust-std.tar.gz",
        ),
    ),
)

shell_command(
    name="cargo",
    command="""
        mkdir cargo
        for TARBALL in cargo.tar.gz rustc.tar.gz rust-std.tar.gz; do
            tar -xzf $TARBALL --strip-components=2 -C cargo
        done
    """,
    tools=["tar", "gzip", "mkdir"],
    execution_dependencies=[
        ":compressed-cargo",
        ":compressed-rustc",
        ":compressed-rust-std",
    ],
    output_directories=["cargo"],
)
