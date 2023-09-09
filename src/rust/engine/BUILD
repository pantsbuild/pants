# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

_RELEASE = env("MODE") == "release"
_RUST_MODE = "--release" if _RELEASE else ""
_OUTPUT_DIR = "release" if _RELEASE else "debug"

files(
    name="rust_sources",
    sources=[
        "Cargo.lock",
        "build.rs",
        "**/Cargo.toml",
        "**/*.rs",
        "**/*.proto",
        ".cargo/config",
    ],
)

shell_sources(name="shell")

shell_command(
    name="engine-and-client",
    command=f"./sandboxed_cargo.sh build {_RUST_MODE} --features=extension-module -p engine -p client",
    execution_dependencies=[
        "./sandboxed_cargo.sh:shell",
        ":rust_sources",
        "3rdparty/tools/protoc:protoc",
        "3rdparty/tools/python3:python3",
        "3rdparty/tools/rust:rust-toolchain",
    ],
    extra_env_vars=["CHROOT={chroot}", "MODE"],
    tools=["cc", "ld", "as", "ar"],
    output_files=[
        f"target/{_OUTPUT_DIR}/libengine.so",
        f"target/{_OUTPUT_DIR}/pants",
    ],
    timeout=600,
)
