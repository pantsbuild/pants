# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

file(
    name="compressed-python-build-standalone-3.9",
    source=per_platform(
        linux_arm64=http_source(
            url="https://github.com/indygreg/python-build-standalone/releases/download/20230507/cpython-3.9.16+20230507-aarch64-unknown-linux-gnu-install_only.tar.gz",
            len=23583066,
            sha256="f629b75ebfcafe9ceee2e796b7e4df5cf8dbd14f3c021afca078d159ab797acf",
            filename="python-build-standalone.tar.gz",
        ),
        linux_x86_64=http_source(
            url="https://github.com/indygreg/python-build-standalone/releases/download/20230507/cpython-3.9.16+20230507-x86_64-unknown-linux-gnu-install_only.tar.gz",
            len=25738357,
            sha256="2b6e146234a4ef2a8946081fc3fbfffe0765b80b690425a49ebe40b47c33445b",
            filename="python-build-standalone.tar.gz",
        ),
        macos_arm64=http_source(
            url="https://github.com/indygreg/python-build-standalone/releases/download/20230507/cpython-3.9.16+20230507-aarch64-apple-darwin-install_only.tar.gz",
            len=16634170,
            sha256="c1de1d854717a6245f45262ef1bb17b09e2c587590e7e3f406593c143ff875bd",
            filename="python-build-standalone.tar.gz",
        ),
        macos_x86_64=http_source(
            url="https://github.com/indygreg/python-build-standalone/releases/download/20230507/cpython-3.9.16+20230507-x86_64-apple-darwin-install_only.tar.gz",
            len=16908516,
            sha256="3abc4d5fbbc80f5f848f280927ac5d13de8dc03aabb6ae65d8247cbb68e6f6bf",
            filename="python-build-standalone.tar.gz",
        ),
    ),
)

shell_command(
    name="python3",
    command="tar -xzf python-build-standalone.tar.gz",
    tools=["tar", "gzip"],
    execution_dependencies=[":compressed-python-build-standalone-3.9"],
    output_directories=["python"],
)
