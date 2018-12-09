# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.binaries.binary_tool import NativeTool


class ProtocForGRPC(NativeTool):
  options_scope = 'protoc-for-grpcio-sys'
  default_version = '2.4.1'
  name = 'protoc'
