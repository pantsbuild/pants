import grpc
from org.pantsbuild.example.service import service_pb2
from org.pantsbuild.example.service import service_pb2_grpc


if __name__ == '__main__':
    print('hello world from grpcio client!')
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = service_pb2_grpc.ExampleServiceStub(channel)
        hello_response = stub.Hello(service_pb2.HelloRequest(action='hello'))
        print(hello_response)
        bye_response = stub.Hello(service_pb2.HelloRequest(action='bye'))
        print(bye_response)
