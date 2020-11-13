# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class Grpcio(PythonToolBase):
    options_scope = "grpcio"

    grpcio_version = "1.17.1"
    default_version = f"grpcio=={grpcio_version}"
    default_extra_requirements = [
        f"grpcio-tools=={grpcio_version}",
        # The grpcio-tools distribution depends on setuptools but does not declare the dependency.
        # See: https://github.com/grpc/grpc/issues/24746
        #
        # We pick setuptools 44.0.0 since its the last setuptools version compatible with both
        # Python 2 and Python 3.
        "setuptools==44.0.0",
    ]

    default_entry_point = "grpc_tools.protoc"
