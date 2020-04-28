# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This target must be build with protoc that recognizes `option go_package`
# ./pants run contrib/go/examples/src/go/distance/ --protoc-gen-go-protobuf-version=3.11.4
go_binary(
  dependencies=[
    'contrib/go/examples/src/protobuf/org/pantsbuild/example/route:route-go',
  ]
)

