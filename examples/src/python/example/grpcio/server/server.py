# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import time
from concurrent import futures

import grpc
from org.pantsbuild.example.grpcio.imports import imports_pb2, imports_pb2_grpc
from org.pantsbuild.example.grpcio.service import service_pb2, service_pb2_grpc


class ExampleHelloServer(service_pb2_grpc.ExampleServiceServicer):
    def Hello(self, request, context):
        print("request with action: [{}]".format(request.action))
        reply = service_pb2.HelloReply()
        reply.response = "{} from server!".format(request.action)
        return reply


class ImportsServiceServer(imports_pb2_grpc.ImportsServiceServicer):
    def HelloImports(self, request, context):
        print("request with action: [{}]".format(request.hello_request.action))
        hello_reply = service_pb2.HelloReply(
            response="{} from imports server!".format(request.hello_request.action)
        )
        reply = imports_pb2.HelloImportsReply(hello_reply=hello_reply)
        return reply


def run_server():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))

    service_pb2_grpc.add_ExampleServiceServicer_to_server(ExampleHelloServer(), server)
    imports_pb2_grpc.add_ImportsServiceServicer_to_server(ImportsServiceServer(), server)

    server.add_insecure_port("[::]:50051")
    server.start()

    print("Server is running...")
    print("(hit Ctrl+C to stop)")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == "__main__":
    run_server()
