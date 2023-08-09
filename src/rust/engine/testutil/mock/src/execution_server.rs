// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::any::type_name;
use std::collections::VecDeque;
use std::fmt::Debug;
use std::iter::FromIterator;
use std::net::SocketAddr;
use std::ops::Deref;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use futures::{FutureExt, Stream};
use grpc_util::hyper_util::AddrIncomingWithStream;
use hashing::Digest;
use parking_lot::Mutex;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::gen::build::bazel::semver::SemVer;
use protos::gen::google::longrunning::{
  operations_server::Operations, operations_server::OperationsServer, CancelOperationRequest,
  DeleteOperationRequest, GetOperationRequest, ListOperationsRequest, ListOperationsResponse,
  Operation,
};
use protos::require_digest;
use remexec::{
  action_cache_server::ActionCache, action_cache_server::ActionCacheServer,
  capabilities_server::Capabilities, capabilities_server::CapabilitiesServer,
  execution_server::Execution, execution_server::ExecutionServer, ActionResult, CacheCapabilities,
  ExecuteRequest, ExecutionCapabilities, GetActionResultRequest, GetCapabilitiesRequest,
  ServerCapabilities, UpdateActionResultRequest, WaitExecutionRequest,
};
use tonic::metadata::MetadataMap;
use tonic::transport::Server;
use tonic::{Request, Response, Status};

///
/// Represents an expected API call from the REv2 client. The data carried by each enum
/// variant are the parameters to verify and the results to return to the client.
///
#[derive(Debug)]
#[allow(clippy::large_enum_variant)] // GetActionResult variant is larger than others
pub enum ExpectedAPICall {
  Execute {
    execute_request: ExecuteRequest,
    stream_responses: Result<Vec<MockOperation>, Status>,
  },
  WaitExecution {
    operation_name: String,
    stream_responses: Result<Vec<MockOperation>, Status>,
  },
  GetOperation {
    operation_name: String,
    operation: MockOperation,
  },
  GetActionResult {
    action_digest: Digest,
    response: Result<ActionResult, Status>,
  },
}

///
/// A MockOperation to be used with MockExecution.
///
/// If the op is None, the MockExecution will drop the channel, triggering cancelation on the
/// client. If the duration is not None, it represents a delay before either responding or
/// canceling for the operation.
///
#[derive(Debug)]
pub struct MockOperation {
  pub op: Result<Option<Operation>, Status>,
  pub duration: Option<Duration>,
}

impl MockOperation {
  pub fn new(op: Operation) -> MockOperation {
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
  local_addr: SocketAddr,
  shutdown_sender: Option<tokio::sync::oneshot::Sender<()>>,
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
    let mock_responder2 = mock_responder.clone();

    let addr = format!("127.0.0.1:{}", port.unwrap_or(0))
      .parse()
      .expect("failed to parse IP address");
    let incoming = hyper::server::conn::AddrIncoming::bind(&addr).expect("failed to bind port");
    let local_addr = incoming.local_addr();
    let incoming = AddrIncomingWithStream(incoming);

    let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel::<()>();

    tokio::spawn(async move {
      let mut server = Server::builder();
      let router = server
        .add_service(ExecutionServer::new(mock_responder2.clone()))
        .add_service(OperationsServer::new(mock_responder2.clone()))
        .add_service(CapabilitiesServer::new(mock_responder2.clone()))
        .add_service(ActionCacheServer::new(mock_responder2));

      router
        .serve_with_incoming_shutdown(incoming, shutdown_receiver.map(drop))
        .await
        .unwrap();
    });

    TestServer {
      mock_responder,
      local_addr,
      shutdown_sender: Some(shutdown_sender),
    }
  }

  ///
  /// The address on which this server is listening over insecure HTTP transport.
  ///
  pub fn address(&self) -> String {
    format!("http://{}", self.local_addr)
  }
}

impl Drop for TestServer {
  fn drop(&mut self) {
    self.shutdown_sender.take().unwrap().send(()).unwrap();

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
            .deref(),
        )),
        MockResponder::display_all(&self.mock_responder.received_messages.deref().lock())
      );
      if std::thread::panicking() {
        eprintln!(
          "TestServer missing requests, but not panicking because caller is already panicking: {message}"
        );
      } else {
        assert_eq!(remaining_expected_responses, 0, "{message}",);
      }
    }
  }
}

#[derive(Debug)]
pub struct ReceivedMessage {
  pub message_type: String,
  pub message: Box<dyn prost::Message>,
  pub received_at: Instant,
  pub headers: MetadataMap,
}

#[derive(Clone, Debug)]
pub struct MockResponder {
  mock_execution: MockExecution,
  pub received_messages: Arc<Mutex<Vec<ReceivedMessage>>>,
  pub cancelation_requests: Arc<Mutex<Vec<CancelOperationRequest>>>,
}

impl MockResponder {
  fn new(mock_execution: MockExecution) -> MockResponder {
    MockResponder {
      mock_execution,
      received_messages: Arc::new(Mutex::new(vec![])),
      cancelation_requests: Arc::new(Mutex::new(vec![])),
    }
  }

  fn log<T: prost::Message + Clone + Sized + 'static>(&self, request: &Request<T>) {
    let headers = request.metadata().clone();

    let message = request.get_ref().clone();

    self.received_messages.lock().push(ReceivedMessage {
      message_type: type_name::<T>().to_string(),
      message: Box::new(message),
      received_at: Instant::now(),
      headers,
    });
  }

  fn display_all<D: Debug>(items: &[D]) -> String {
    items
      .iter()
      .map(|i| format!("{i:?}\n"))
      .collect::<Vec<_>>()
      .concat()
  }

  fn stream_from_mock_operations(
    operations: Vec<MockOperation>,
  ) -> Pin<Box<dyn Stream<Item = Result<Operation, Status>> + Send + Sync>> {
    let stream = async_stream::stream! {
      for op in operations {
        if let Some(d) = op.duration {
          tokio::time::sleep(d).await;
        }

        if let Ok(Some(op)) = op.op {
          yield Ok(op);
        } else if let Err(status) = op.op {
          yield Err(status);
          break;
        }
      }
    };
    Box::pin(stream)
  }
}

#[tonic::async_trait]
impl Execution for MockResponder {
  type ExecuteStream = Pin<Box<dyn Stream<Item = Result<Operation, Status>> + Send + Sync>>;

  async fn execute(
    &self,
    request: Request<ExecuteRequest>,
  ) -> Result<Response<Self::ExecuteStream>, Status> {
    self.log(&request);
    let request = request.into_inner();

    let expected_api_call = self.mock_execution.expected_api_calls.lock().pop_front();
    match expected_api_call {
      Some(ExpectedAPICall::Execute {
        execute_request,
        stream_responses,
      }) => {
        if request == execute_request {
          match stream_responses {
            Ok(operations) => {
              return Ok(Response::new(Self::stream_from_mock_operations(operations)));
            }
            Err(rpc_status) => Err(rpc_status),
          }
        } else {
          return Err(Status::invalid_argument(format!(
            "Did not expect this request. Expected: {execute_request:?}, Got: {request:?}"
          )));
        }
      }

      Some(api_call) => {
        return Err(Status::invalid_argument(format!(
          "Execute endpoint called. Expected: {api_call:?}"
        )));
      }

      None => Err(Status::invalid_argument(
        "Execute endpoint called. Did not expect this call.".to_owned(),
      )),
    }
  }

  type WaitExecutionStream = Pin<Box<dyn Stream<Item = Result<Operation, Status>> + Send + Sync>>;

  async fn wait_execution(
    &self,
    request: Request<WaitExecutionRequest>,
  ) -> Result<Response<Self::WaitExecutionStream>, Status> {
    self.log(&request);

    let request = request.into_inner();

    let expected_api_call = self.mock_execution.expected_api_calls.lock().pop_front();
    match expected_api_call {
      Some(ExpectedAPICall::WaitExecution {
        operation_name,
        stream_responses,
      }) => {
        if request.name == operation_name {
          match stream_responses {
            Ok(operations) => {
              return Ok(Response::new(Self::stream_from_mock_operations(operations)));
            }
            Err(rpc_status) => Err(rpc_status),
          }
        } else {
          return Err(Status::invalid_argument(format!(
            "Did not expect WaitExecution for this operation. Expected: {:?}, Got: {:?}",
            operation_name, request.name
          )));
        }
      }

      Some(api_call) => {
        return Err(Status::invalid_argument(format!(
          "WaitExecution endpoint called. Expected: {api_call:?}",
        )));
      }

      None => Err(Status::invalid_argument(
        "WaitExecution endpoint called. Did not expect this call.".to_owned(),
      )),
    }
  }
}

#[tonic::async_trait]
impl Operations for MockResponder {
  async fn list_operations(
    &self,
    _: Request<ListOperationsRequest>,
  ) -> Result<Response<ListOperationsResponse>, Status> {
    Err(Status::unimplemented("".to_owned()))
  }

  async fn get_operation(
    &self,
    request: Request<GetOperationRequest>,
  ) -> Result<Response<Operation>, Status> {
    self.log(&request);

    let request = request.into_inner();

    let expected_api_call = self.mock_execution.expected_api_calls.lock().pop_front();
    match expected_api_call {
      Some(ExpectedAPICall::GetOperation {
        operation_name,
        operation,
      }) => {
        if request.name == operation_name {
          if let Some(d) = operation.duration {
            tokio::time::sleep(d).await;
          }
          if let Ok(Some(op)) = operation.op {
            // Complete the channel with the op.
            Ok(Response::new(op))
          } else if let Err(status) = operation.op {
            Err(status)
          } else {
            Err(Status::internal(
              "Test setup did not specify an error or operation".to_owned(),
            ))
          }
        } else {
          Err(Status::invalid_argument(format!(
            "Did not expect GetOperation for this operation. Expected: {:?}, Got: {:?}",
            operation_name, request.name
          )))
        }
      }

      Some(api_call) => Err(Status::invalid_argument(format!(
        "GetOperation endpoint called. Expected: {api_call:?}",
      ))),

      None => Err(Status::invalid_argument(
        "GetOperation endpoint called. Did not expect this call.".to_owned(),
      )),
    }
  }

  async fn delete_operation(
    &self,
    _: Request<DeleteOperationRequest>,
  ) -> Result<Response<()>, Status> {
    Err(Status::unimplemented("".to_owned()))
  }

  async fn cancel_operation(
    &self,
    request: Request<CancelOperationRequest>,
  ) -> Result<Response<()>, Status> {
    self.log(&request);
    let request = request.into_inner();
    self.cancelation_requests.lock().push(request);
    Ok(Response::new(()))
  }
}

#[tonic::async_trait]
impl ActionCache for MockResponder {
  async fn get_action_result(
    &self,
    request: Request<GetActionResultRequest>,
  ) -> Result<Response<ActionResult>, Status> {
    self.log(&request);

    let request = request.into_inner();

    let expected_api_call = self.mock_execution.expected_api_calls.lock().pop_front();
    match expected_api_call {
      Some(ExpectedAPICall::GetActionResult {
        action_digest,
        response,
      }) => {
        let action_digest_from_request: Digest =
          match require_digest(request.action_digest.as_ref()) {
            Ok(d) => d,
            Err(e) => {
              return Err(Status::invalid_argument(format!(
                "GetActionResult endpoint called with bad digest: {e:?}",
              )));
            }
          };

        if action_digest_from_request == action_digest {
          match response {
            Ok(action_result) => Ok(Response::new(action_result)),
            Err(status) => Err(status),
          }
        } else {
          Err(Status::invalid_argument(format!(
            "Did not expect request with this action digest. Expected: {:?}, Got: {:?}",
            action_digest, request.action_digest
          )))
        }
      }

      Some(api_call) => Err(Status::invalid_argument(format!(
        "GetActionResult endpoint called. Expected: {api_call:?}",
      ))),

      None => Err(Status::invalid_argument(
        "GetActionResult endpoint called. Did not expect this call.".to_owned(),
      )),
    }
  }

  async fn update_action_result(
    &self,
    _: Request<UpdateActionResultRequest>,
  ) -> Result<Response<ActionResult>, Status> {
    Err(Status::unimplemented("".to_owned()))
  }
}

#[tonic::async_trait]
impl Capabilities for MockResponder {
  async fn get_capabilities(
    &self,
    _: Request<GetCapabilitiesRequest>,
  ) -> Result<Response<ServerCapabilities>, Status> {
    let response = ServerCapabilities {
      cache_capabilities: Some(CacheCapabilities {
        digest_functions: vec![remexec::digest_function::Value::Sha256 as i32],
        max_batch_total_size_bytes: 0,
        ..CacheCapabilities::default()
      }),
      execution_capabilities: Some(ExecutionCapabilities {
        digest_function: remexec::digest_function::Value::Sha256 as i32,
        exec_enabled: true,
        ..ExecutionCapabilities::default()
      }),
      low_api_version: Some(SemVer {
        major: 2,
        minor: 0,
        patch: 0,
        ..SemVer::default()
      }),
      high_api_version: Some(SemVer {
        major: 2,
        minor: 0,
        patch: 0,
        ..SemVer::default()
      }),
      ..ServerCapabilities::default()
    };

    Ok(Response::new(response))
  }
}
