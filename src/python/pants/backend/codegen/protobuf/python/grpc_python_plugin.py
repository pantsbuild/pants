# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform


class GrpcPythonPlugin(ExternalTool):
    options_scope = "grpc-python-plugin"
    help = "The gRPC Protobuf plugin for Python."

    # https://github.com/nhurden/protoc-gen-grpc-python-prebuilt maintains a
    # composite versioning strategy with both the grpc plugin version and the
    # version of "protoc-gen-grpc-python-prebuilt" that built it
    default_version = "v0.2.0+v1.73.1"
    default_known_versions = [
        "v0.2.0+v1.73.1|linux_arm64|91da9e959553224a4f3977313b1e0ec45ba966536da28b76041e151bf218502a|13965288",
        "v0.2.0+v1.73.1|linux_x86_64|72d864bb3832d8f094f3c9add308724565a446cc8a19f041f8752848068b70a1|13197104",
        "v0.2.0+v1.73.1|macos_arm64|ea26c8b5c1a534fe271b8a2d8a2683f25d75de4d767fbf0b9e78d43a0ea228ce|33011832",
        "v0.2.0+v1.73.1|macos_x86_64|ea26c8b5c1a534fe271b8a2d8a2683f25d75de4d767fbf0b9e78d43a0ea228ce|33011832",
        # Old versions from binaries.pantsbuild.org
        "1.32.0|macos_arm64 |b2db586656463841aa2fd4aab34fb6bd3ef887b522d80e4f2f292146c357f533|6215304|https://binaries.pantsbuild.org/bin/grpc_python_plugin/1.32.0/macos/x86_64/grpc_python_plugin",
        "1.32.0|macos_x86_64|b2db586656463841aa2fd4aab34fb6bd3ef887b522d80e4f2f292146c357f533|6215304|https://binaries.pantsbuild.org/bin/grpc_python_plugin/1.32.0/macos/x86_64/grpc_python_plugin",
        "1.32.0|linux_arm64 |9365e728c603d64735963074340994245d324712344f63557ef3630864dd9f52|5233664|https://binaries.pantsbuild.org/bin/grpc_python_plugin/1.32.0/linux/arm64/grpc_python_plugin",
        "1.32.0|linux_x86_64|1af99df9bf733c17a75cbe379f3f9d9ff1627d8a8035ea057c3c78575afe1687|4965728|https://binaries.pantsbuild.org/bin/grpc_python_plugin/1.32.0/linux/x86_64/grpc_python_plugin",
    ]

    def generate_url(self, plat: Platform) -> str:
        prebuilt_version, grpc_version = self.version.split("+")
        plat_str = {
            "macos_arm64": "macos-universal",
            "macos_x86_64": "macos-universal",
            "linux_arm64": "linux-aarch64",
            "linux_x86_64": "linux-x86_64",
        }[plat.value]

        return f"https://github.com/nhurden/protoc-gen-grpc-python-prebuilt/releases/download/{prebuilt_version}/protoc-gen-grpc-python-{plat_str}-{grpc_version}"
