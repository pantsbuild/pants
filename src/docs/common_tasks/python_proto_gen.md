# Python gRPC + protobufs

## Problem
You have `.proto` files defining protobufs and grpc services and you want Pants to generate Python code from them that you can use from a Python application.

## Solution
Create `python_grpc_library` targets and use the gen goal to generate code from the `.proto` files. There is a codegen task grpcio-run, that uses Python's grpcio library https://grpc.io/ and generates python code from .proto files.

## Usage

in a `BUILD` file near your proto files, create a `python_grpcio_library` target with your protos as a `sources`.

```build
python_grpcio_library(
  sources=['service.proto'],
  dependencies=[
    '3rdparty/python:protobuf',
  ]
)
```

Then, you can add a dependency on this target in your python binary's `BUILD` file `dependencies` section:

```build
python_binary(
  source='server.py',
  dependencies=[
    'src/protobuf/org/pantsbuild/example/grpcio/service',
  ],
)
```

## Example:
An example Python gRPC client/server can be found in [/examples/src/python/example/grpcio](https://github.com/pantsbuild/pants/tree/master/examples/src/python/example/grpcio)

to create a gRPC server execute
```bash
./pants run src/python/example/grpcio/server
```

and when server is running, run client example:
```bash
./pants run src/python/example/grpcio/client
```

generated code can be found as usual in pants output directory:
```bash
./pants.d/gen/grpcio-run/current/examples.src.protobuf.org.pantsbuild.example.service.service/current/org/pantsbuild/example/service
```
