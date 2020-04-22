# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import grpc
from org.pantsbuild.example.grpcio.imports import imports_pb2, imports_pb2_grpc
from org.pantsbuild.example.grpcio.service import service_pb2


def run_example():
    print("hello world from grpcio imports_client!")
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = imports_pb2_grpc.ImportsServiceStub(channel)
        try:

            hello_request = service_pb2.HelloRequest(action="hello with imports")
            request = imports_pb2.HelloImportsRequest(hello_request=hello_request)
            reply = stub.HelloImports(request)
        except grpc.RpcError as error:
            if error.code() == grpc.StatusCode.UNAVAILABLE:
                print(
                    "[ERROR] Connection to server is unavailable. You should create a server instance first."
                )
                print(
                    "To start a gRPC server, execute: `./pants run examples/src/python/example/grpcio/server`"
                )
            else:
                print(
                    "An error occurred! Error code: [{}] Error details: [{}]".format(
                        error.code(), error.details()
                    )
                )
        else:
            print(reply.hello_reply.response)
            print("[SUCCESS]")


if __name__ == "__main__":
    run_example()
