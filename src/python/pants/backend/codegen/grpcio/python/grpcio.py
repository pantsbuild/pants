# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class Grpcio(PythonToolBase):
  grpcio_version = '1.17.1'

  options_scope = 'grpcio'
  default_requirements = [
    'grpcio-tools=={}'.format(grpcio_version),
    'grpcio=={}'.format(grpcio_version),
  ]
  default_entry_point = 'grpc_tools.protoc'
