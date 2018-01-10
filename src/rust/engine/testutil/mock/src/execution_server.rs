use std::collections::VecDeque;
use std::fmt::Debug;
use std::iter::FromIterator;
use std::ops::Deref;
use std::sync::{Arc, Mutex};

use bazel_protos;
use grpcio;
use protobuf;

#[derive(Clone, Debug)]
pub struct MockExecution {
  name: String,
  execute_request: bazel_protos::remote_execution::ExecuteRequest,
  operation_responses: Arc<Mutex<VecDeque<bazel_protos::operations::Operation>>>,
}

impl MockExecution {
  ///
  /// # Arguments:
  ///  * `name` - The name of the operation. It is assumed that all operation_responses use this
  ///             name.
  ///  * `execute_request` - The expected ExecuteRequest.
  ///  * `operation_responses` - Vec of Operation response for Execution or GetOperation requests.
  ///                            Will be returned in order.
  ///
  pub fn new(
    name: String,
    execute_request: bazel_protos::remote_execution::ExecuteRequest,
    operation_responses: Vec<bazel_protos::operations::Operation>,
  ) -> Result<MockExecution, String> {
    let error = operation_responses
      .iter()
      .find(|o| o.get_name() != name)
      .map(|bad| {
        Err(format!(
          "All operation responses must have a name matching the MockExecution's name ({}) but \
at least one did not ({:?})",
          name,
          bad
        ))
      });
    match error {
      Some(x) => x,
      None => Ok(MockExecution {
        name: name,
        execute_request: execute_request,
        operation_responses: Arc::new(Mutex::new(VecDeque::from(operation_responses))),
      }),
    }
  }
}

///
/// A server which will answer ExecuteRequest and GetOperation gRPC requests with pre-canned
/// responses.
///
pub struct TestServer {
  mock_responder: MockResponder,
  server_transport: grpcio::Server,
}

impl TestServer {
  ///
  /// # Arguments
  /// * `mock_execution` - The canned responses to issue. Returns the MockExecution's
  ///                      operation_responses in order to any ExecuteRequest or GetOperation
  ///                      requests.
  ///                      If an ExecuteRequest request is received which is not equal to this
  ///                      MockExecution's execute_request, an error will be returned.
  ///                      If a GetOperation request is received whose name is not equal to this
  ///                      MockExecution's name, or more requests are received than stub responses
  ///                      are available for, an error will be returned.
  pub fn new(mock_execution: MockExecution) -> TestServer {
    let mock_responder = MockResponder::new(mock_execution);

    let env = Arc::new(grpcio::Environment::new(1));
    let mut server_transport = grpcio::ServerBuilder::new(env)
      .register_service(bazel_protos::remote_execution_grpc::create_execution(
        mock_responder.clone(),
      ))
      .register_service(bazel_protos::operations_grpc::create_operations(
        mock_responder.clone(),
      ))
      .bind("localhost", 0)
      .build()
      .unwrap();
    server_transport.start();

    TestServer {
      mock_responder: mock_responder,
      server_transport,
    }
  }

  ///
  /// The address on which this server is listening over insecure HTTP transport.
  ///
  pub fn address(&self) -> String {
    let bind_addr = self.server_transport.bind_addrs().first().unwrap();
    format!("{}:{}", bind_addr.0, bind_addr.1)
  }
}

impl Drop for TestServer {
  fn drop(&mut self) {
    let remaining_expected_responses = self
      .mock_responder
      .mock_execution
      .operation_responses
      .lock()
      .unwrap()
      .len();
    assert_eq!(
      remaining_expected_responses,
      0,
      "Expected {} more requests. Remaining expected responses:\n{}\nReceived requests:\n{}",
      remaining_expected_responses,
      MockResponder::display_all(&Vec::from_iter(
        self
          .mock_responder
          .mock_execution
          .operation_responses
          .lock()
          .unwrap()
          .clone(),
      )),
      MockResponder::display_all(&self
        .mock_responder
        .received_messages
        .deref()
        .lock()
        .unwrap())
    )
  }
}

#[derive(Clone, Debug)]
pub struct MockResponder {
  mock_execution: MockExecution,
  received_messages: Arc<Mutex<Vec<(String, Box<protobuf::Message>)>>>,
}

impl MockResponder {
  fn new(mock_execution: MockExecution) -> MockResponder {
    MockResponder {
      mock_execution: mock_execution,
      received_messages: Arc::new(Mutex::new(vec![])),
    }
  }

  fn log<T: protobuf::Message + Sized>(&self, message: T) {
    self.received_messages.lock().unwrap().push((
      message
        .descriptor()
        .name()
        .to_string(),
      Box::new(message),
    ));
  }

  fn display_all<D: Debug>(items: &Vec<D>) -> String {
    items
      .iter()
      .map(|i| format!("{:?}\n", i))
      .collect::<Vec<_>>()
      .concat()
  }

  fn send_next_operation(
    &self,
    sink: grpcio::UnarySink<super::bazel_protos::operations::Operation>,
  ) {
    match self
      .mock_execution
      .operation_responses
      .lock()
      .unwrap()
      .pop_front() {
      Some(op) => {
        sink.success(op.clone());
      }
      None => {
        sink.fail(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::InvalidArgument,
          Some("Did not expect this request".to_string()),
        ));
      }
    }
  }
}

impl bazel_protos::remote_execution_grpc::Execution for MockResponder {
  fn execute(
    &self,
    _: grpcio::RpcContext,
    req: bazel_protos::remote_execution::ExecuteRequest,
    sink: grpcio::UnarySink<super::bazel_protos::operations::Operation>,
  ) {
    self.log(req.clone());

    if self.mock_execution.execute_request != req {
      sink.fail(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::InvalidArgument,
        Some("Did not expect this request".to_string()),
      ));
      return;
    }

    self.send_next_operation(sink);
  }
}

impl bazel_protos::operations_grpc::Operations for MockResponder {
  fn get_operation(
    &self,
    _: grpcio::RpcContext,
    req: bazel_protos::operations::GetOperationRequest,
    sink: grpcio::UnarySink<bazel_protos::operations::Operation>,
  ) {
    self.log(req.clone());

    self.send_next_operation(sink)
  }

  fn list_operations(
    &self,
    _: grpcio::RpcContext,
    _: bazel_protos::operations::ListOperationsRequest,
    sink: grpcio::UnarySink<bazel_protos::operations::ListOperationsResponse>,
  ) {
    sink.fail(grpcio::RpcStatus::new(
      grpcio::RpcStatusCode::Unimplemented,
      None,
    ));
  }

  fn delete_operation(
    &self,
    _: grpcio::RpcContext,
    _: bazel_protos::operations::DeleteOperationRequest,
    sink: grpcio::UnarySink<bazel_protos::empty::Empty>,
  ) {
    sink.fail(grpcio::RpcStatus::new(
      grpcio::RpcStatusCode::Unimplemented,
      None,
    ));
  }

  fn cancel_operation(
    &self,
    _: grpcio::RpcContext,
    _: bazel_protos::operations::CancelOperationRequest,
    sink: grpcio::UnarySink<bazel_protos::empty::Empty>,
  ) {
    sink.fail(grpcio::RpcStatus::new(
      grpcio::RpcStatusCode::Unimplemented,
      None,
    ));
  }
}
