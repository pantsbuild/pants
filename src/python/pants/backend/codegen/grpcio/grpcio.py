# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


logger = logging.getLogger(__name__)


class Grpcio(PythonToolBase):
  grpcio_version = '1.17.1'

  options_scope = 'grpcio'
  default_requirements = [
    'grpcio-tools=={}'.format(grpcio_version),
    'grpcio=={}'.format(grpcio_version),
  ]
  default_entry_point = 'grpc_tools.protoc'
  pass
