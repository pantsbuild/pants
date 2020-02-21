# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class Grpcio(PythonToolBase):
    options_scope = "grpcio"

    grpcio_version = "1.17.1"
    default_version = f"grpcio=={grpcio_version}"
    default_extra_requirements = [f"grpcio-tools=={grpcio_version}"]

    default_entry_point = "grpc_tools.protoc"
