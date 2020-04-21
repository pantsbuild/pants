# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import grpc
from org.pantsbuild.example.grpcio.service import service_pb2, service_pb2_grpc


def run_example():
    print("hello world from grpcio service_client!")
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = service_pb2_grpc.ExampleServiceStub(channel)
        try:
            hello_response = stub.Hello(service_pb2.HelloRequest(action="hello"))
            bye_response = stub.Hello(service_pb2.HelloRequest(action="bye"))
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
            print(hello_response)
            print(bye_response)
            print("[SUCCESS]")


if __name__ == "__main__":
    run_example()
