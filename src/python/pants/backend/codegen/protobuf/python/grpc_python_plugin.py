# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import TemplatedExternalTool


class GrpcPythonPlugin(TemplatedExternalTool):
    options_scope = "grpc-python-plugin"
    help = "The gRPC Protobuf plugin for Python."
    deprecated_options_scope = "grpc_python_plugin"
    deprecated_options_scope_removal_version = "2.8.0.dev0"

    default_version = "1.32.0"
    default_known_versions = [
        "1.32.0|macos_arm64 |b2db586656463841aa2fd4aab34fb6bd3ef887b522d80e4f2f292146c357f533|6215304",
        "1.32.0|macos_x86_64|b2db586656463841aa2fd4aab34fb6bd3ef887b522d80e4f2f292146c357f533|6215304",
        "1.32.0|linux_x86_64|1af99df9bf733c17a75cbe379f3f9d9ff1627d8a8035ea057c3c78575afe1687|4965728",
    ]
    default_url_template = (
        "https://binaries.pantsbuild.org/bin/grpc_python_plugin/{version}/"
        "{platform}/x86_64/grpc_python_plugin"
    )
    default_url_platform_mapping = {
        "macos_arm64": "macos",
        "macos_x86_64": "macos",
        "linux_x86_64": "linux",
    }
