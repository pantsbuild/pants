# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

file(
    name="compressed-protoc",
    source=per_platform(
        linux_arm64=http_source(
            url="https://github.com/protocolbuffers/protobuf/releases/download/v24.3/protoc-24.3-linux-aarch_64.zip",
            len=2971115,
            sha256="77a5a41f3e9712af6a35de13143b9b2b77f075aa1ab18a63cca4483b30f6e3cd",
            filename="protoc.zip",
        ),
        linux_x86_64=http_source(
            url="https://github.com/protocolbuffers/protobuf/releases/download/v24.3/protoc-24.3-linux-x86_64.zip",
            len=3005508,
            sha256="fc793561283d9ea6813fb757ae54f1afea6770afcd930904bdf3e590910420aa",
            filename="protoc.zip",
        ),
        macos_arm64=http_source(
            url="https://github.com/protocolbuffers/protobuf/releases/download/v24.3/protoc-24.3-osx-aarch_64.zip",
            len=2089053,
            sha256="cca53adb73a6686dd60bb3b0da33961e6b9dab1f833c851b5e1bb7b5df02b36f",
            filename="protoc.zip",
        ),
        macos_x86_64=http_source(
            url="https://github.com/protocolbuffers/protobuf/releases/download/v24.3/protoc-24.3-osx-x86_64.zip",
            len=2121387,
            sha256="13b45cdcde9b2101e982de897d5490cfd81dfa181605749c23982379ba0e3288",
            filename="protoc.zip",
        ),
    ),
)

shell_command(
    name="protoc",
    command="unzip protoc.zip -d protoc",
    tools=["unzip"],
    execution_dependencies=[":compressed-protoc"],
    output_directories=["protoc"],
)
