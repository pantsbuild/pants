# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
    name="rust_sources",
    sources=[
        "Cargo.lock",
        "build.rs",
        "**/Cargo.toml",
        "**/*.rs",
        "!**/*tests.rs",
        "**/*.proto",
        ".cargo/config",
        "rust-toolchain",
    ],
)

shell_sources(name="shell")

shell_command(
    name="engine-and-client",
    command=f"./cargo_build_shim.sh --features=extension-module -p engine -p client",
    execution_dependencies=[
        ":rust_sources",
        "./cargo_build_shim.sh:shell",
        "3rdparty/tools/python3:python3",
    ],
    extra_env_vars=["CHROOT={chroot}", "MODE"],
    tools=["bash", "cc", "ld", "as", "ar", "cargo", "protoc", "python3.9"],
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
