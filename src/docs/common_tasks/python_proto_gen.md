# Generate Python code from Protoc Definitions

## Problem
I would like to have a task, to generate python code from protobufs and grpc services.

## Solution
There is a new codegen task grpcio-run, to execute python's grpcio library https://grpc.io/ and generate python code from .proto files.

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

Then, you can relay on this target in your python code `BUILD` file `dependencies` section:

```build
python_binary(
  name='server',
  dependencies=[
#    [...]
    'examples/src/protobuf/org/pantsbuild/example/grpcio/service'
  ],
  source='server.py',
)
```

## Example:
Respectful examples can be found in /examples/src/python/example/grpcio

to create a gRPC server execute
```bash
./pants run examples/src/python/example/grpcio/server
```

and when server is running, run client example:
```bash
./pants run examples/src/python/example/grpcio/client
```

generated code can be found as usual in pants output directory:
```bash
./pants.d/gen/grpcio-run/current/examples.src.protobuf.org.pantsbuild.example.service.service/current/org/pantsbuild/example/service
```
