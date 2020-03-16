# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name='server',
  dependencies=[
    'examples/3rdparty/python:grpcio',
    'examples/src/protobuf/org/pantsbuild/example/grpcio/service',
    'examples/src/protobuf/org/pantsbuild/example/grpcio/imports',
  ],
  sources=['server.py'],
)
