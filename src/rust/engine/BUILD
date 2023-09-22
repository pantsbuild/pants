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

files(
    name="all_rust_source_files",
    sources=["**/*.rs"],
)

experimental_test_shell_command(
    name="checks-rust-banned-imports",
    command=f"""
        BAD_FILES=$(grep -r -l -E "^use std::sync::.*(Mutex|RwLock)" {build_file_dir()})
        if [ -n "$BAD_FILES" ]; then
            echo "The following files contained banned \\`std::sync\\` imports (\\`Mutex\\` and \\`RWLock\\`).";
            echo "(Hint: Use the \\`parking_lot::\\` equivalent)";
            echo "";
            echo "$BAD_FILES";
            exit 1;
        else
            exit 0;
        fi
    """,
    tools=["grep", "echo"],
    execution_dependencies=[":all_rust_source_files"],
    workdir="/",
)
