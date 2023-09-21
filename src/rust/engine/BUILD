# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
    name="rust_sources",
    sources=[
        "Cargo.lock",
        "build.rs",
        "VERSION",
        "**/Cargo.toml",
        "**/*.rs",
        "!**/*tests.rs",
        "**/*.proto",
        ".cargo/config",
    ],
)

file(
    name="rust-toolchain",
    source="rust-toolchain",
)

_RELTYPE_FLAG = "" if env("MODE") == "debug" else "--release"

shell_command(
    name="engine-and-client",
    command=f"""
        PATH="${{PATH}}:{{chroot}}/3rdparty/tools/python3/python/bin";
        PATH="${{PATH}}:{{chroot}}/3rdparty/tools/protoc/protoc/bin";
        PATH="${{PATH}}:{{chroot}}/3rdparty/tools/rust/cargo/bin";

        cargo build {_RELTYPE_FLAG} --features=extension-module -p engine -p client
    """,
    execution_dependencies=[
        ":rust_sources",
        "3rdparty/tools/protoc:protoc",
        "3rdparty/tools/python3:python3",
        "3rdparty/tools/rust:cargo",
    ],
    tools=["bash", "cc", "ld", "as", "ar"],
    output_files=[
        f"target/debug/libengine.so",
        f"target/debug/libengine.dylib",
        f"target/debug/pants",
        f"target/release/libengine.so",
        f"target/release/libengine.dylib",
        f"target/release/pants",
    ],
    timeout=600,
)
