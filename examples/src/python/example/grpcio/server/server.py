# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import time
from concurrent import futures

import grpc
from org.pantsbuild.example.service import service_pb2, service_pb2_grpc


class ExampleHelloServer(service_pb2_grpc.ExampleServiceServicer):

  def Hello(self, request, context):
    print('request with action: [{}]'.format(request.action))
    reply = service_pb2.HelloReply()
    reply.response = '{} from server!'.format(request.action)
    return reply


def run_server():
  server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))

  service_pb2_grpc.add_ExampleServiceServicer_to_server(ExampleHelloServer(), server)

  server.add_insecure_port('[::]:50051')
  server.start()

  print('Server is running...')
  print('(hit Ctrl+C to stop)')
  try:
    while True:
      time.sleep(10)
  except KeyboardInterrupt:
    server.stop(0)


if __name__ == '__main__':
  run_server()
