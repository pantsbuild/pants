# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name='service',
  dependencies=[
    'examples/3rdparty/python:grpcio',
    'examples/src/protobuf/org/pantsbuild/example/grpcio/service',
  ],
  sources=['service_client.py'],
)

python_binary(
  name='imports',
  dependencies=[
    'examples/3rdparty/python:grpcio',
    'examples/src/protobuf/org/pantsbuild/example/grpcio/imports',
  ],
  sources=['imports_client.py'],
)
