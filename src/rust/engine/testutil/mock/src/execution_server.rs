use std::collections::{HashMap, VecDeque};
use std::fmt::Debug;
use std::iter::FromIterator;
use std::ops::Deref;
use std::sync::Arc;
use std::thread::sleep;
use std::time::Duration;
use std::time::Instant;

use futures::compat::{Future01CompatExt, Sink01CompatExt};
use futures::future::{FutureExt, TryFutureExt};
use futures::sink::SinkExt;
use grpcio::RpcStatus;
use parking_lot::Mutex;

///
/// Represents an expected API call from the REv2 client. The data carried by each enum
/// variant are the parameters to verify and the results to return to the client.
///
#[derive(Clone, Debug)]
pub enum ExpectedAPICall {
  Execute {
    execute_request: bazel_protos::remote_execution::ExecuteRequest,
    stream_responses: Result<Vec<MockOperation>, grpcio::RpcStatus>,
  },
  WaitExecution {
    operation_name: String,
    stream_responses: Result<Vec<MockOperation>, grpcio::RpcStatus>,
  },
  GetOperation {
    operation_name: String,
    operation: MockOperation,
  },
}

///
/// A MockOperation to be used with MockExecution.
///
/// If the op is None, the MockExecution will drop the channel, triggering cancelation on the
/// client. If the duration is not None, it represents a delay before either responding or
/// canceling for the operation.
///
#[derive(Clone, Debug)]
pub struct MockOperation {
  pub op: Result<Option<bazel_protos::operations::Operation>, grpcio::RpcStatus>,
  pub duration: Option<Duration>,
}

impl MockOperation {
  pub fn new(op: bazel_protos::operations::Operation) -> MockOperation {
    MockOperation {
      op: Ok(Some(op)),
      duration: None,
    }
  }
}

#[derive(Clone, Debug)]
pub struct MockExecution {
  expected_api_calls: Arc<Mutex<VecDeque<ExpectedAPICall>>>,
}

impl MockExecution {
  ///
  /// # Arguments:
  ///  * `name` - The name of the operation. It is assumed that all operation_responses use this
  ///             name.
  ///  * `expected_api_calls` - Vec of ExpectedAPICall instances representing the API calls
  ///                            to expect from the client. Will be returned in order.
  ///
  pub fn new(expected_api_calls: Vec<ExpectedAPICall>) -> MockExecution {
    MockExecution {
      expected_api_calls: Arc::new(Mutex::new(VecDeque::from(expected_api_calls))),
    }
  }
}

///
/// A server which will answer Execute/WaitExecution and GetOperation/CancelOperation gRPC
/// requests with pre-canned responses.
///
pub struct TestServer {
  pub mock_responder: MockResponder,
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
  pub fn new(mock_execution: MockExecution, port: Option<u16>) -> TestServer {
    let mock_responder = MockResponder::new(mock_execution);

    let env = Arc::new(grpcio::Environment::new(1));
    let mut server_transport = grpcio::ServerBuilder::new(env)
      .register_service(bazel_protos::remote_execution_grpc::create_execution(
        mock_responder.clone(),
      ))
      .register_service(bazel_protos::operations_grpc::create_operations(
        mock_responder.clone(),
      ))
      .bind("localhost", port.unwrap_or(0))
      .build()
      .unwrap();
    server_transport.start();

    TestServer {
      mock_responder,
      server_transport,
    }
  }

  ///
  /// The address on which this server is listening over insecure HTTP transport.
  ///
  pub fn address(&self) -> String {
    let bind_addr = self.server_transport.bind_addrs().next().unwrap();
    format!("{}:{}", bind_addr.0, bind_addr.1)
  }
}

impl Drop for TestServer {
  fn drop(&mut self) {
    let remaining_expected_responses = self
      .mock_responder
      .mock_execution
      .expected_api_calls
      .lock()
      .len();
    if remaining_expected_responses != 0 {
      let message = format!(
        "Expected {} more requests. Remaining expected responses:\n{}\nReceived requests:\n{}",
        remaining_expected_responses,
        MockResponder::display_all(&Vec::from_iter(
          self
            .mock_responder
            .mock_execution
            .expected_api_calls
            .lock()
            .clone(),
        )),
        MockResponder::display_all(&self.mock_responder.received_messages.deref().lock())
      );
      if std::thread::panicking() {
        eprintln!(
          "TestServer missing requests, but not panicking because caller is already panicking: {}",
          message
        );
      } else {
        assert_eq!(remaining_expected_responses, 0, "{}", message,);
      }
    }
  }
}

#[derive(Debug)]
pub struct ReceivedMessage {
  pub message_type: String,
  pub message: Box<dyn protobuf::Message>,
  pub received_at: Instant,
  pub headers: HashMap<String, Vec<u8>>,
}

#[derive(Clone, Debug)]
pub struct MockResponder {
  mock_execution: MockExecution,
  pub received_messages: Arc<Mutex<Vec<ReceivedMessage>>>,
  pub cancelation_requests: Arc<Mutex<Vec<bazel_protos::operations::CancelOperationRequest>>>,
}

impl MockResponder {
  fn new(mock_execution: MockExecution) -> MockResponder {
    MockResponder {
      mock_execution,
      received_messages: Arc::new(Mutex::new(vec![])),
      cancelation_requests: Arc::new(Mutex::new(vec![])),
    }
  }

  fn log<T: protobuf::Message + Sized>(&self, ctx: &grpcio::RpcContext, message: T) {
    let headers = ctx
      .request_headers()
      .iter()
      .map(|(name, value)| (name.to_string(), value.to_vec()))
      .collect();
    self.received_messages.lock().push(ReceivedMessage {
      message_type: message.descriptor().name().to_string(),
      message: Box::new(message),
      received_at: Instant::now(),
      headers,
    });
  }

  fn display_all<D: Debug>(items: &[D]) -> String {
    items
      .iter()
      .map(|i| format!("{:?}\n", i))
      .collect::<Vec<_>>()
      .concat()
  }

  fn spawn_send_to_operation_stream(
    &self,
    ctx: grpcio::RpcContext<'_>,
    sink: grpcio::ServerStreamingSink<bazel_protos::operations::Operation>,
    operations: Vec<MockOperation>,
  ) {
    let mut sink = sink.sink_compat();

    let fut = async move {
      let mut error_to_send: Option<RpcStatus> = None;
      for op in operations {
        if let Some(d) = op.duration {
          tokio::time::delay_for(d).await;
        }

        if let Ok(Some(op)) = op.op {
          let _ = sink.send((op, grpcio::WriteFlags::default())).await;
        } else if let Err(status) = op.op {
          error_to_send = Some(status);
          break;
        }
      }

      let _ = sink.flush().await;

      if let Some(err) = error_to_send {
        let _ = sink.into_inner().fail(err).compat().await;
      } else {
        let _ = sink.close().await;
      }

      Ok(())
    };
    ctx.spawn(fut.boxed().compat());
  }
}

impl bazel_protos::remote_execution_grpc::Execution for MockResponder {
  fn execute(
    &self,
    ctx: grpcio::RpcContext<'_>,
    req: bazel_protos::remote_execution::ExecuteRequest,
    sink: grpcio::ServerStreamingSink<bazel_protos::operations::Operation>,
  ) {
    self.log(&ctx, req.clone());

    let expected_api_call = self.mock_execution.expected_api_calls.lock().pop_front();
    let error_to_send: Option<RpcStatus>;
    match expected_api_call {
      Some(ExpectedAPICall::Execute {
        execute_request,
        stream_responses,
      }) => {
        if req == execute_request {
          match stream_responses {
            Ok(operations) => {
              self.spawn_send_to_operation_stream(ctx, sink, operations);
              return;
            }
            Err(rpc_status) => {
              error_to_send = Some(rpc_status);
            }
          }
        } else {
          error_to_send = Some(grpcio::RpcStatus::new(
            grpcio::RpcStatusCode::INVALID_ARGUMENT,
            Some(format!(
              "Did not expect this request. Expected: {:?}, Got: {:?}",
              execute_request, req
            )),
          ));
        }
      }

      Some(api_call) => {
        error_to_send = Some(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::INVALID_ARGUMENT,
          Some(format!("Execute endpoint called. Expected: {:?}", api_call,)),
        ));
      }

      None => {
        error_to_send = Some(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::INVALID_ARGUMENT,
          Some("Execute endpoint called. Did not expect this call.".to_owned()),
        ));
      }
    }

    if let Some(status) = error_to_send {
      let _ = sink.fail(status);
    }
  }

  fn wait_execution(
    &self,
    ctx: grpcio::RpcContext<'_>,
    req: bazel_protos::remote_execution::WaitExecutionRequest,
    sink: grpcio::ServerStreamingSink<bazel_protos::operations::Operation>,
  ) {
    self.log(&ctx, req.clone());

    let expected_api_call = self.mock_execution.expected_api_calls.lock().pop_front();
    let error_to_send: Option<RpcStatus>;
    match expected_api_call {
      Some(ExpectedAPICall::WaitExecution {
        operation_name,
        stream_responses,
      }) => {
        if req.name == operation_name {
          match stream_responses {
            Ok(operations) => {
              self.spawn_send_to_operation_stream(ctx, sink, operations);
              return;
            }
            Err(rpc_status) => {
              error_to_send = Some(rpc_status);
            }
          }
        } else {
          error_to_send = Some(grpcio::RpcStatus::new(
            grpcio::RpcStatusCode::INVALID_ARGUMENT,
            Some(format!(
              "Did not expect WaitExecution for this operation. Expected: {:?}, Got: {:?}",
              operation_name, req.name
            )),
          ));
        }
      }

      Some(api_call) => {
        error_to_send = Some(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::INVALID_ARGUMENT,
          Some(format!(
            "WaitExecution endpoint called. Expected: {:?}",
            api_call,
          )),
        ));
      }

      None => {
        error_to_send = Some(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::INVALID_ARGUMENT,
          Some("WaitExecution endpoint called. Did not expect this call.".to_owned()),
        ));
      }
    }

    if let Some(status) = error_to_send {
      let _ = sink.fail(status);
    }
  }
}

impl bazel_protos::operations_grpc::Operations for MockResponder {
  fn get_operation(
    &self,
    ctx: grpcio::RpcContext<'_>,
    req: bazel_protos::operations::GetOperationRequest,
    sink: grpcio::UnarySink<bazel_protos::operations::Operation>,
  ) {
    self.log(&ctx, req.clone());

    let expected_api_call = self.mock_execution.expected_api_calls.lock().pop_front();
    let error_to_send: Option<RpcStatus>;
    match expected_api_call {
      Some(ExpectedAPICall::GetOperation {
        operation_name,
        operation,
      }) => {
        if req.name == operation_name {
          if let Some(d) = operation.duration {
            sleep(d);
          }
          if let Ok(Some(op)) = operation.op {
            // Complete the channel with the op.
            sink.success(op);
          } else if let Err(status) = operation.op {
            sink.fail(status);
          }
          return;
        } else {
          error_to_send = Some(grpcio::RpcStatus::new(
            grpcio::RpcStatusCode::INVALID_ARGUMENT,
            Some(format!(
              "Did not expect GetOperation for this operation. Expected: {:?}, Got: {:?}",
              operation_name, req.name
            )),
          ));
        }
      }

      Some(api_call) => {
        error_to_send = Some(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::INVALID_ARGUMENT,
          Some(format!(
            "GetOperation endpoint called. Expected: {:?}",
            api_call,
          )),
        ));
      }

      None => {
        error_to_send = Some(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::INVALID_ARGUMENT,
          Some("GetOperation endpoint called. Did not expect this call.".to_owned()),
        ));
      }
    }

    if let Some(status) = error_to_send {
      let _ = sink.fail(status);
    }
  }

  fn list_operations(
    &self,
    _: grpcio::RpcContext<'_>,
    _: bazel_protos::operations::ListOperationsRequest,
    sink: grpcio::UnarySink<bazel_protos::operations::ListOperationsResponse>,
  ) {
    sink.fail(grpcio::RpcStatus::new(
      grpcio::RpcStatusCode::UNIMPLEMENTED,
      None,
    ));
  }

  fn delete_operation(
    &self,
    _: grpcio::RpcContext<'_>,
    _: bazel_protos::operations::DeleteOperationRequest,
    sink: grpcio::UnarySink<bazel_protos::empty::Empty>,
  ) {
    sink.fail(grpcio::RpcStatus::new(
      grpcio::RpcStatusCode::UNIMPLEMENTED,
      None,
    ));
  }

  fn cancel_operation(
    &self,
    ctx: grpcio::RpcContext<'_>,
    req: bazel_protos::operations::CancelOperationRequest,
    sink: grpcio::UnarySink<bazel_protos::empty::Empty>,
  ) {
    self.log(&ctx, req.clone());
    self.cancelation_requests.lock().push(req);
    sink.success(bazel_protos::empty::Empty::new());
  }
}
