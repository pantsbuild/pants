use std::collections::{BTreeMap, HashMap};
use std::mem::drop;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bazel_protos::{self, call_option};
use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use concrete_time::TimeSpan;
use digest::{Digest as DigestTrait, FixedOutput};
use fs::{self, File, PathStat};
use futures::compat::Future01CompatExt;
use futures::future::{self as future03, FutureExt, TryFutureExt};
use futures01::{future, Future, Stream};
use grpcio;
use hashing::{Digest, Fingerprint};
use libc;
use log::{debug, trace, warn};
use protobuf::{self, Message, ProtobufEnum};
use sha2::Sha256;
use store::{Snapshot, Store, StoreFileByDigest};
use tokio::time::delay_for;

use crate::{
  Context, ExecutionStats, FallibleProcessResultWithPlatform, MultiPlatformProcess, Platform,
  PlatformConstraint, Process, ProcessMetadata,
};
use std;
use std::cmp::min;
use workunit_store::WorkUnitStore;

// Environment variable which is exclusively used for cache key invalidation.
// This may be not specified in an Process, and may be populated only by the
// CommandRunner.
pub const CACHE_KEY_GEN_VERSION_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_GEN_VERSION";

#[derive(Derivative)]
#[derivative(Debug)]
struct CancelRemoteExecutionToken {
  //  CancelRemoteExecutionToken is used to cancel remote execution process
  // if we no longer care about the result, but we think it's still running.
  // Remote execution process can be cancelled by sending CancelOperationRequest.
  #[derivative(Debug = "ignore")]
  operations_client: Arc<bazel_protos::operations_grpc::OperationsClient>,
  operation_name: ::std::string::String,
  #[derivative(Debug = "ignore")]
  executor: task_executor::Executor,
  send_cancellation_on_drop: bool,
}

impl CancelRemoteExecutionToken {
  fn new(
    operations_client: Arc<bazel_protos::operations_grpc::OperationsClient>,
    operation_name: ::std::string::String,
    executor: task_executor::Executor,
  ) -> CancelRemoteExecutionToken {
    CancelRemoteExecutionToken {
      operations_client,
      operation_name,
      executor,
      send_cancellation_on_drop: true,
    }
  }

  fn do_not_send_cancellation_on_drop(&mut self) {
    self.send_cancellation_on_drop = false;
  }
}

impl Drop for CancelRemoteExecutionToken {
  fn drop(&mut self) {
    if self.send_cancellation_on_drop {
      let mut cancel_op_req = bazel_protos::operations::CancelOperationRequest::new();
      cancel_op_req.set_name(self.operation_name.clone());
      let operation_name = self.operation_name.clone();
      match self
        .operations_client
        .cancel_operation_async(&cancel_op_req)
      {
        Ok(receiver) => {
          self.executor.spawn_and_ignore(async move {
            match receiver.compat().await {
              Ok(_) => debug!("Canceled operation {} successfully", operation_name),
              Err(err) => debug!("Failed to cancel operation {}, err {}", operation_name, err),
            }
          });
        }
        Err(err) => debug!(
          "Failed to schedule cancel operation: {}, err {}",
          self.operation_name, err
        ),
      };
    }
  }
}

#[derive(Debug)]
pub enum OperationOrStatus {
  Operation(bazel_protos::operations::Operation),
  Status(bazel_protos::status::Status),
}

#[derive(Clone)]
pub struct CommandRunner {
  metadata: ProcessMetadata,
  headers: BTreeMap<String, String>,
  channel: grpcio::Channel,
  env: Arc<grpcio::Environment>,
  execution_client: Arc<bazel_protos::remote_execution_grpc::ExecutionClient>,
  operations_client: Arc<bazel_protos::operations_grpc::OperationsClient>,
  store: Store,
  platform: Platform,
  executor: task_executor::Executor,
  // We use a buffer time for queuing of process requests so that the process's requested timeout more
  // accurately reflects how long the caller intended the process to last.
  queue_buffer_time: Duration,
  backoff_incremental_wait: Duration,
  backoff_max_wait: Duration,
}

#[derive(Debug, PartialEq)]
pub enum ExecutionError {
  // String is the error message.
  Fatal(String),
  // Digests are Files and Directories which have been reported to be missing. May be incomplete.
  MissingDigests(Vec<Digest>),
  // String is the operation name which can be used to poll the GetOperation gRPC API.
  NotFinished(String),
  // String is the error message.
  Retryable(String),
}

#[derive(Default)]
pub struct ExecutionHistory {
  attempts: Vec<ExecutionStats>,
  current_attempt: ExecutionStats,
}

impl ExecutionHistory {
  fn total_attempt_count(&self) -> usize {
    self.attempts.len() + 1
  }
}

impl CommandRunner {
  // The Execute API used to be unary, and became streaming. The contract of the streaming API is
  // that if the client closes the stream after one request, it should continue to function exactly
  // like the unary API.
  // For maximal compatibility with servers, we fall back to this unary-like behavior, and control
  // our own polling rates.
  // In the future, we may want to remove this behavior if servers reliably support the full stream
  // behavior.

  fn platform(&self) -> Platform {
    self.platform
  }

  fn oneshot_execute(
    &self,
    execute_request: &Arc<bazel_protos::remote_execution::ExecuteRequest>,
    build_id: String,
  ) -> BoxFuture<OperationOrStatus, String> {
    let stream = try_future!(self
      .execution_client
      .execute_opt(
        &execute_request,
        try_future!(call_option(&self.headers, Some(build_id),))
      )
      .map_err(rpcerror_to_string));
    stream
      .take(1)
      .into_future()
      // If there was a response, drop the _stream to disconnect so that the server doesn't keep
      // the connection alive and continue sending on it.
      .map(|(maybe_operation, stream)| {
        drop(stream);
        maybe_operation
      })
      // If there was an error, drop the _stream to disconnect so that the server doesn't keep the
      // connection alive and continue sending on it.
      .map_err(|(error, stream)| {
        drop(stream);
        error
      })
      .then(move |maybe_operation_result| match maybe_operation_result {
        Ok(Some(operation)) => Ok(OperationOrStatus::Operation(operation)),
        Ok(None) => {
          Err("Didn't get proper stream response from server during remote execution".to_owned())
        }
        Err(err) => rpcerror_to_status_or_string(err).map(OperationOrStatus::Status),
      })
      .to_boxed()
  }
}

// TODO(pantsbuild/pants#8039) Need to impl Drop on command runner  so that when the BoxFuture goes out of scope
// we cancel a potential RPC. So we need to distinguish local vs. remote
// requests and save enough state to BoxFuture or another abstraction around our execution results
impl super::CommandRunner for CommandRunner {
  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    for compatible_constraint in vec![
      &(PlatformConstraint::None, PlatformConstraint::None),
      &(self.platform.into(), PlatformConstraint::None),
      &(
        self.platform.into(),
        PlatformConstraint::current_platform_constraint().unwrap(),
      ),
    ]
    .iter()
    {
      if let Some(compatible_req) = req.0.get(compatible_constraint) {
        return Some(compatible_req.clone());
      }
    }
    None
  }

  ///
  /// Runs a command via a gRPC service implementing the Bazel Remote Execution API
  /// (https://docs.google.com/document/d/1AaGk7fOPByEvpAbqeXIyE8HX_A3_axxNnvroblTZ_6s/edit).
  ///
  /// If the CommandRunner has a Store, files will be uploaded to the remote CAS as needed.
  /// Note that it does not proactively upload files to a remote CAS. This is because if we will
  /// get a cache hit, uploading the files was wasted time and bandwidth, and if the remote CAS
  /// already has some files, uploading them all is a waste. Instead, we look at the responses we
  /// get back from the server, and upload the files it says it's missing.
  ///
  /// In the future, we may want to do some clever things like proactively upload files which the
  /// user has changed, or files which aren't known to the local git repository, but these are
  /// optimizations to shave off a round-trip in the future.
  ///
  /// Loops until the server gives a response, either successful or error. Does not have any
  /// timeout: polls in a tight loop.
  ///
  /// TODO: Request jdk_home be created if set.
  ///
  fn run(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> BoxFuture<FallibleProcessResultWithPlatform, String> {
    let platform = self.platform();
    let compatible_underlying_request = self.extract_compatible_request(&req).unwrap();
    let operations_client = self.operations_client.clone();
    let store = self.store.clone();
    let execute_request_result =
      make_execute_request(&compatible_underlying_request, self.metadata.clone());

    let Process {
      description,
      timeout,
      input_files,
      ..
    } = compatible_underlying_request;

    let description2 = description.clone();

    match execute_request_result {
      Ok((action, command, execute_request)) => {
        let command_runner = self.clone();
        let execute_request = Arc::new(execute_request);

        let mut history = ExecutionHistory::default();

        self
          .store_proto_locally(&command)
          .join(self.store_proto_locally(&action))
          .and_then({
            let store = store.clone();
            move |(command_digest, action_digest)| {
              store.ensure_remote_has_recursive(
                vec![command_digest, action_digest, input_files],
              )
            }
          })
          .and_then({
            let execute_request = execute_request.clone();
            let command_runner = command_runner.clone();
            let build_id = context.build_id.to_owned();
            move |summary| {
              history.current_attempt += summary;
              trace!(
                "Executing remotely request: {:?} (command: {:?})",
                execute_request,
                command
              );
              command_runner
                .oneshot_execute(&execute_request, build_id)
                .join(future::ok(history))
            }
          })
          .map({
            let operations_client = operations_client.clone();
            let executor = command_runner.executor.clone();
            move |(operation, history)| {
              let maybe_cancel_remote_exec_token = match operation {
                OperationOrStatus::Operation(ref operation) => Some(
                  CancelRemoteExecutionToken::new(operations_client, operation.name.clone(), executor),
                ),
                _ => None,
              };
              (operation, history, maybe_cancel_remote_exec_token)
            }
          })
          .and_then(
            move |(operation, history, maybe_cancel_remote_exec_token)| {
              let start_time = Instant::now();

              future::loop_fn(
                (history, operation, maybe_cancel_remote_exec_token, 0),
                move |(mut history, operation, maybe_cancel_remote_exec_token, iter_num)| {
                  let description = description.clone();

                  let execute_request = execute_request.clone();
                  let store = store.clone();
                  let operations_client = operations_client.clone();
                  let command_runner = command_runner.clone();
                  let build_id = context.build_id.to_string();

                  let f = command_runner
                    .extract_execute_response(operation, &mut history);
                  f.then(move |value| {
                    match value {
                      Ok(result) => {
                        if let Some(mut cancel_remote_exec_token) = maybe_cancel_remote_exec_token {
                          cancel_remote_exec_token.do_not_send_cancellation_on_drop();
                        }
                        future::ok(future::Loop::Break(result)).to_boxed()
                      },
                      Err(err) => {
                        match err {
                          ExecutionError::Fatal(err) => {
                            // In case of receiving  Fatal error from the server it is assumed that
                            // remote execution is no longer running
                            if let Some(mut cancel_remote_exec_token) = maybe_cancel_remote_exec_token {
                              cancel_remote_exec_token.do_not_send_cancellation_on_drop();
                            }
                            future::err(err).to_boxed()
                          }
                          ExecutionError::Retryable(message) => {
                            command_runner.retry_execution(
                              execute_request,
                              future::done({
                                if history.total_attempt_count() >= 5 {
                                  Err(format!("Gave up retrying remote execution after {} retriable attempts; last failure: {}", history.total_attempt_count(), message))
                                } else {
                                  trace!("Got retryable error from server; retrying. Error: {}", message);
                                  Ok(())
                                }
                              }).to_boxed(),
                              build_id,
                              history,
                              maybe_cancel_remote_exec_token,
                            )
                          },
                          ExecutionError::MissingDigests(missing_digests) => {
                            trace!(
                              "Server reported missing digests ({:?}); trying to upload: {:?}",
                              history.current_attempt,
                              missing_digests,
                            );

                            command_runner.retry_execution(
                              execute_request,
                              store.ensure_remote_has_recursive(missing_digests).map(|_| ()).to_boxed(),
                              build_id,
                              history,
                              maybe_cancel_remote_exec_token,
                            )
                          },
                          ExecutionError::NotFinished(operation_name) => {
                            let mut operation_request =
                                bazel_protos::operations::GetOperationRequest::new();
                            operation_request.set_name(operation_name.clone());

                            let backoff_period = min(
                              command_runner.backoff_max_wait,
                              (1 + iter_num) * command_runner.backoff_incremental_wait,
                            );

                            // Take the grpc result and cancel the op if too much time has passed.
                            // This timeout is here to make sure that if something goes wrong, e.g.
                            // the connection hangs, we don't poll forever.
                            let elapsed = start_time.elapsed();
                            let total_timeout = timeout.map(|t| t + command_runner.queue_buffer_time);

                            if total_timeout.map(|t| elapsed > t).unwrap_or(false) {
                              let ExecutionHistory {
                                mut attempts,
                                mut current_attempt,
                              } = history;
                              current_attempt.remote_execution = Some(elapsed);
                              attempts.push(current_attempt);
                              future::ok(future::Loop::Break(FallibleProcessResultWithPlatform {
                                stdout: Bytes::from(format!(
                                  "Exceeded timeout of {:?} ({:?} for the process and {:?} for remoting buffer time) with {:?} for operation {}, {}",
                                  total_timeout, timeout, command_runner.queue_buffer_time, elapsed, operation_name, description
                                )),
                                stderr: Bytes::new(),
                                exit_code: -libc::SIGTERM,
                                output_directory: hashing::EMPTY_DIGEST,
                                execution_attempts: attempts,
                                platform,
                              }))
                                  .to_boxed()
                            } else {
                              // maybe the delay here should be the min of remaining time and the backoff period
                              delay_for(backoff_period)
                                  .unit_error()
                                  .boxed()
                                  .compat()
                                  .map_err(move |()| {
                                    format!(
                                      "Future-Delay errored at operation result polling for {}, {}",
                                      operation_name, description
                                    )
                                  })
                                  .and_then(move |_| {
                              operations_client
                                  .get_operation_opt(
                                    &operation_request,
                                    call_option(&command_runner.headers, Some(build_id))?,
                                  )
                                  .or_else(move |err| {
                                    rpcerror_recover_cancelled(operation_request.take_name(), err)
                                  }).map_err(rpcerror_to_string)
                                  .map(OperationOrStatus::Operation)
                            })
                                    .map(move |operation| {
                                      future::Loop::Continue((
                                        history,
                                        operation,
                                        maybe_cancel_remote_exec_token,
                                        iter_num + 1,
                                      ))
                                    })
                                  .to_boxed()
                            }
                          }
                        }
                      }
                    }
                  })
                },
              )
            },
          )
          .map(move |resp| {
            let mut attempts = String::new();
            for (i, attempt) in resp.execution_attempts.iter().enumerate() {
              attempts += &format!("\nAttempt {}: {:?}", i, attempt);
            }
            debug!(
              "Finished remote exceution of {} after {} attempts: Stats: {}",
              description2,
              resp.execution_attempts.len(),
              attempts
            );
            resp
          })
          .to_boxed()
      }
      Err(err) => future::err(err).to_boxed(),
    }
  }
}

impl CommandRunner {
  pub fn new(
    address: &str,
    metadata: ProcessMetadata,
    root_ca_certs: Option<Vec<u8>>,
    oauth_bearer_token: Option<String>,
    headers: BTreeMap<String, String>,
    store: Store,
    platform: Platform,
    executor: task_executor::Executor,
    queue_buffer_time: Duration,
    backoff_incremental_wait: Duration,
    backoff_max_wait: Duration,
  ) -> Result<CommandRunner, String> {
    let env = Arc::new(grpcio::EnvBuilder::new().build());
    let channel = {
      let builder = grpcio::ChannelBuilder::new(env.clone());
      if let Some(root_ca_certs) = root_ca_certs {
        let creds = grpcio::ChannelCredentialsBuilder::new()
          .root_cert(root_ca_certs)
          .build();
        builder.secure_connect(address, creds)
      } else {
        builder.connect(address)
      }
    };
    let execution_client = Arc::new(bazel_protos::remote_execution_grpc::ExecutionClient::new(
      channel.clone(),
    ));
    let operations_client = Arc::new(bazel_protos::operations_grpc::OperationsClient::new(
      channel.clone(),
    ));

    let mut headers = headers;
    if let Some(oauth_bearer_token) = oauth_bearer_token {
      headers.insert(
        String::from("authorization"),
        format!("Bearer {}", oauth_bearer_token),
      );
    }

    // Validate that any configured static headers are valid.
    call_option(&headers, None)?;

    let command_runner = CommandRunner {
      metadata,
      headers,
      channel,
      env,
      execution_client,
      operations_client,
      store,
      platform,
      executor,
      queue_buffer_time,
      backoff_incremental_wait,
      backoff_max_wait,
    };

    Ok(command_runner)
  }

  fn store_proto_locally<P: protobuf::Message>(
    &self,
    proto: &P,
  ) -> impl Future<Item = Digest, Error = String> {
    let store = self.store.clone();
    let maybe_command_bytes = proto
      .write_to_bytes()
      .map_err(|e| format!("Error serializing proto {:?}", e));

    // Box and pin a stdlib future, and then convert it to a futures01 future via `compat()`.
    Box::pin(async move {
      let command_bytes = maybe_command_bytes?;
      store
        .store_file_bytes(Bytes::from(command_bytes), true)
        .await
        .map_err(|e| format!("Error saving proto to local store: {:?}", e))
    })
    .compat()
  }

  // Only public for tests
  pub(crate) fn extract_execute_response(
    &self,
    operation_or_status: OperationOrStatus,
    attempts: &mut ExecutionHistory,
  ) -> BoxFuture<FallibleProcessResultWithPlatform, ExecutionError> {
    trace!("Got operation response: {:?}", operation_or_status);

    let status = match operation_or_status {
      OperationOrStatus::Operation(mut operation) => {
        if !operation.get_done() {
          return future::err(ExecutionError::NotFinished(operation.take_name())).to_boxed();
        }
        if operation.has_error() {
          return future::err(ExecutionError::Fatal(format_error(&operation.get_error())))
            .to_boxed();
        }
        if !operation.has_response() {
          return future::err(ExecutionError::Fatal(
            "Operation finished but no response supplied".to_string(),
          ))
          .to_boxed();
        }

        let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
        try_future!(execute_response
          .merge_from_bytes(operation.get_response().get_value())
          .map_err(|e| ExecutionError::Fatal(format!("Invalid ExecuteResponse: {:?}", e))));
        trace!("Got (nested) execute response: {:?}", execute_response);
        if execute_response.get_result().has_execution_metadata() {
          let metadata = execute_response.get_result().get_execution_metadata();
          let workunit_state = workunit_store::expect_workunit_state();
          let workunit_store = workunit_state.store;
          let parent_id = workunit_state.parent_id;
          let result_cached = execute_response.get_cached_result();

          match TimeSpan::from_start_and_end(
            metadata.get_queued_timestamp(),
            metadata.get_worker_start_timestamp(),
            "remote queue",
          ) {
            Ok(time_span) => {
              attempts.current_attempt.remote_queue = Some(time_span.duration.into());
              maybe_add_workunit(
                result_cached,
                "remote execution action scheduling",
                time_span,
                parent_id.clone(),
                &workunit_store,
              );
            }
            Err(s) => warn!("{}", s),
          };

          match TimeSpan::from_start_and_end(
            metadata.get_input_fetch_start_timestamp(),
            metadata.get_input_fetch_completed_timestamp(),
            "remote input fetch",
          ) {
            Ok(time_span) => {
              attempts.current_attempt.remote_input_fetch = Some(time_span.duration.into());
              maybe_add_workunit(
                result_cached,
                "remote execution worker input fetching",
                time_span,
                parent_id.clone(),
                &workunit_store,
              );
            }
            Err(s) => warn!("{}", s),
          }

          match TimeSpan::from_start_and_end(
            metadata.get_execution_start_timestamp(),
            metadata.get_execution_completed_timestamp(),
            "remote execution",
          ) {
            Ok(time_span) => {
              attempts.current_attempt.remote_execution = Some(time_span.duration.into());
              maybe_add_workunit(
                result_cached,
                "remote execution worker command executing",
                time_span,
                parent_id.clone(),
                &workunit_store,
              );
            }
            Err(s) => warn!("{}", s),
          }

          match TimeSpan::from_start_and_end(
            metadata.get_output_upload_start_timestamp(),
            metadata.get_output_upload_completed_timestamp(),
            "remote output store",
          ) {
            Ok(time_span) => {
              attempts.current_attempt.remote_output_store = Some(time_span.duration.into());
              maybe_add_workunit(
                result_cached,
                "remote execution worker output uploading",
                time_span,
                parent_id,
                &workunit_store,
              );
            }
            Err(s) => warn!("{}", s),
          }
          attempts.current_attempt.was_cache_hit = execute_response.cached_result;
        }

        let status = execute_response.take_status();
        if grpcio::RpcStatusCode::from(status.get_code()) == grpcio::RpcStatusCode::OK {
          let mut execution_attempts = std::mem::replace(&mut attempts.attempts, vec![]);
          execution_attempts.push(attempts.current_attempt);
          return populate_fallible_execution_result(
            self.store.clone(),
            execute_response,
            execution_attempts,
            self.platform,
          )
          .map_err(ExecutionError::Fatal)
          .to_boxed();
        }
        status
      }
      OperationOrStatus::Status(status) => status,
    };

    match grpcio::RpcStatusCode::from(status.get_code()) {
      grpcio::RpcStatusCode::OK => unreachable!(),
      grpcio::RpcStatusCode::FAILED_PRECONDITION => {
        if status.get_details().len() != 1 {
          return future::err(ExecutionError::Fatal(format!(
            "Received multiple details in FailedPrecondition ExecuteResponse's status field: {:?}",
            status.get_details()
          )))
          .to_boxed();
        }
        let details = status.get_details().get(0).unwrap();
        let mut precondition_failure = bazel_protos::error_details::PreconditionFailure::new();
        if details.get_type_url()
          != format!(
            "type.googleapis.com/{}",
            precondition_failure.descriptor().full_name()
          )
        {
          return future::err(ExecutionError::Fatal(format!(
            "Received FailedPrecondition, but didn't know how to resolve it: {},\
             protobuf type {}",
            status.get_message(),
            details.get_type_url()
          )))
          .to_boxed();
        }
        try_future!(precondition_failure
          .merge_from_bytes(details.get_value())
          .map_err(|e| ExecutionError::Fatal(format!(
            "Error deserializing FailedPrecondition proto: {:?}",
            e
          ))));

        let mut missing_digests = Vec::with_capacity(precondition_failure.get_violations().len());

        for violation in precondition_failure.get_violations() {
          if violation.get_field_type() != "MISSING" {
            return future::err(ExecutionError::Fatal(format!(
              "Didn't know how to process PreconditionFailure violation: {:?}",
              violation
            )))
            .to_boxed();
          }
          let parts: Vec<_> = violation.get_subject().split('/').collect();
          if parts.len() != 3 || parts[0] != "blobs" {
            return future::err(ExecutionError::Fatal(format!(
              "Received FailedPrecondition MISSING but didn't recognize subject {}",
              violation.get_subject()
            )))
            .to_boxed();
          }
          let digest = Digest(
            try_future!(Fingerprint::from_hex_string(parts[1]).map_err(|e| {
              ExecutionError::Fatal(format!("Bad digest in missing blob: {}: {}", parts[1], e))
            })),
            try_future!(parts[2]
              .parse::<usize>()
              .map_err(|e| ExecutionError::Fatal(format!(
                "Missing blob had bad size: {}: {}",
                parts[2], e
              )))),
          );
          missing_digests.push(digest);
        }
        if missing_digests.is_empty() {
          return future::err(ExecutionError::Fatal(
            "Error from remote execution: FailedPrecondition, but no details".to_owned(),
          ))
          .to_boxed();
        }
        future::err(ExecutionError::MissingDigests(missing_digests)).to_boxed()
      }
      code => match code {
        grpcio::RpcStatusCode::ABORTED
        | grpcio::RpcStatusCode::INTERNAL
        | grpcio::RpcStatusCode::RESOURCE_EXHAUSTED
        | grpcio::RpcStatusCode::UNAVAILABLE
        | grpcio::RpcStatusCode::UNKNOWN => {
          future::err(ExecutionError::Retryable(status.get_message().to_owned())).to_boxed()
        }
        _ => future::err(ExecutionError::Fatal(format!(
          "Error from remote execution: {:?}: {:?}",
          code,
          status.get_message()
        )))
        .to_boxed(),
      },
    }
    .to_boxed()
  }

  #[allow(clippy::type_complexity)]
  fn retry_execution(
    &self,
    execute_request: Arc<bazel_protos::remote_execution::ExecuteRequest>,
    prefix_future: BoxFuture<(), String>,
    build_id: String,
    history: ExecutionHistory,
    maybe_cancel_remote_exec_token: Option<CancelRemoteExecutionToken>,
  ) -> BoxFuture<
    future::Loop<
      FallibleProcessResultWithPlatform,
      (
        ExecutionHistory,
        OperationOrStatus,
        Option<CancelRemoteExecutionToken>,
        u32,
      ),
    >,
    String,
  > {
    if let Some(mut cancel_remote_exec_token) = maybe_cancel_remote_exec_token {
      cancel_remote_exec_token.do_not_send_cancellation_on_drop();
    }

    let ExecutionHistory {
      mut attempts,
      current_attempt,
    } = history;
    attempts.push(current_attempt);
    let history = ExecutionHistory {
      attempts,
      current_attempt: ExecutionStats::default(),
    };

    let command_runner = self.clone();
    prefix_future
      .and_then(move |()| command_runner.oneshot_execute(&execute_request, build_id))
      .map({
        let operations_client = self.operations_client.clone();
        let executor = self.executor.clone();
        move |operation| {
          let maybe_cancel_remote_exec_token = match operation {
            OperationOrStatus::Operation(ref operation) => Some(CancelRemoteExecutionToken::new(
              operations_client,
              operation.name.clone(),
              executor,
            )),
            _ => None,
          };
          future::Loop::Continue((
            history,
            operation,
            maybe_cancel_remote_exec_token,
            // Reset `iter_num` for a new Execute attempt:
            0,
          ))
        }
      })
      .to_boxed()
  }
}

fn maybe_add_workunit(
  result_cached: bool,
  name: &str,
  time_span: concrete_time::TimeSpan,
  parent_id: Option<String>,
  workunit_store: &WorkUnitStore,
) {
  //  TODO: workunits for scheduling, fetching, executing and uploading should be recorded
  //   only if '--reporting-zipkin-trace-v2' is set
  if !result_cached {
    workunit_store.add_completed_workunit(name.to_string(), time_span, parent_id);
  }
}

pub fn make_execute_request(
  req: &Process,
  metadata: ProcessMetadata,
) -> Result<
  (
    bazel_protos::remote_execution::Action,
    bazel_protos::remote_execution::Command,
    bazel_protos::remote_execution::ExecuteRequest,
  ),
  String,
> {
  let mut command = bazel_protos::remote_execution::Command::new();
  command.set_arguments(protobuf::RepeatedField::from_vec(req.argv.clone()));
  for (name, value) in &req.env {
    if name.as_str() == CACHE_KEY_GEN_VERSION_ENV_VAR_NAME {
      return Err(format!(
        "Cannot set env var with name {} as that is reserved for internal use by pants",
        CACHE_KEY_GEN_VERSION_ENV_VAR_NAME
      ));
    }
    let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
    env.set_name(name.to_string());
    env.set_value(value.to_string());
    command.mut_environment_variables().push(env);
  }

  let ProcessMetadata {
    instance_name,
    cache_key_gen_version,
    mut platform_properties,
  } = metadata;

  if let Some(cache_key_gen_version) = cache_key_gen_version {
    let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
    env.set_name(CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_string());
    env.set_value(cache_key_gen_version);
    command.mut_environment_variables().push(env);
  }
  let mut output_files = req
    .output_files
    .iter()
    .map(|p| {
      p.to_str()
        .map(str::to_owned)
        .ok_or_else(|| format!("Non-UTF8 output file path: {:?}", p))
    })
    .collect::<Result<Vec<String>, String>>()?;
  output_files.sort();
  command.set_output_files(protobuf::RepeatedField::from_vec(output_files));

  let mut output_directories = req
    .output_directories
    .iter()
    .map(|p| {
      p.to_str()
        .map(str::to_owned)
        .ok_or_else(|| format!("Non-UTF8 output directory path: {:?}", p))
    })
    .collect::<Result<Vec<String>, String>>()?;
  output_directories.sort();
  command.set_output_directories(protobuf::RepeatedField::from_vec(output_directories));

  if let Some(working_directory) = &req.working_directory {
    command.set_working_directory(
      working_directory
        .to_str()
        .map(str::to_owned)
        .unwrap_or_else(|| panic!("Non-UTF8 working directory path: {:?}", working_directory)),
    )
  }

  if req.jdk_home.is_some() {
    // Ideally, the JDK would be brought along as part of the input directory, but we don't
    // currently have support for that. Scoot supports this property, and will symlink .jdk to a
    // system-installed JDK https://github.com/twitter/scoot/pull/391 - we should probably come to
    // some kind of consensus across tools as to how this should work; RBE appears to work by
    // allowing you to specify a jdk-version platform property, and it will put a JDK at a
    // well-known path in the docker container you specify in which to run.
    platform_properties.push(("JDK_SYMLINK".to_owned(), ".jdk".to_owned()));
  }
  platform_properties.push(("target_platform".to_owned(), req.target_platform.into()));

  for (name, value) in platform_properties {
    command.mut_platform().mut_properties().push({
      let mut property = bazel_protos::remote_execution::Platform_Property::new();
      property.set_name(name.clone());
      property.set_value(value.clone());
      property
    });
  }

  let mut action = bazel_protos::remote_execution::Action::new();
  action.set_command_digest((&digest(&command)?).into());
  action.set_input_root_digest((&req.input_files).into());

  let mut execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  if let Some(instance_name) = instance_name {
    execute_request.set_instance_name(instance_name);
  }
  execute_request.set_action_digest((&digest(&action)?).into());

  Ok((action, command, execute_request))
}

pub fn populate_fallible_execution_result(
  store: Store,
  execute_response: bazel_protos::remote_execution::ExecuteResponse,
  execution_attempts: Vec<ExecutionStats>,
  platform: Platform,
) -> impl Future<Item = FallibleProcessResultWithPlatform, Error = String> {
  extract_stdout(&store, &execute_response)
    .join(extract_stderr(&store, &execute_response))
    .join(extract_output_files(store, &execute_response))
    .and_then(move |((stdout, stderr), output_directory)| {
      Ok(FallibleProcessResultWithPlatform {
        stdout: stdout,
        stderr: stderr,
        exit_code: execute_response.get_result().get_exit_code(),
        output_directory: output_directory,
        execution_attempts: execution_attempts,
        platform,
      })
    })
}

fn extract_stdout(
  store: &Store,
  execute_response: &bazel_protos::remote_execution::ExecuteResponse,
) -> BoxFuture<Bytes, String> {
  if execute_response.get_result().has_stdout_digest() {
    let store = store.clone();
    let stdout_digest_result: Result<Digest, String> =
      execute_response.get_result().get_stdout_digest().into();
    let stdout_digest =
      try_future!(stdout_digest_result.map_err(|err| format!("Error extracting stdout: {}", err)));
    Box::pin(async move {
      let (bytes, _metadata) = store
        .load_file_bytes_with(stdout_digest, |v| v)
        .map_err(move |error| {
          format!(
            "Error fetching stdout digest ({:?}): {:?}",
            stdout_digest, error
          )
        })
        .await?
        .ok_or_else(|| {
          format!(
            "Couldn't find stdout digest ({:?}), when fetching.",
            stdout_digest
          )
        })?;
      Ok(bytes)
    })
    .compat()
    .to_boxed()
  } else {
    let store = store.clone();
    let stdout_raw = Bytes::from(execute_response.get_result().get_stdout_raw());
    let stdout_copy = stdout_raw.clone();
    Box::pin(async move {
      store
        .store_file_bytes(stdout_raw, true)
        .map_err(move |error| format!("Error storing raw stdout: {:?}", error))
        .await?;
      Ok(stdout_copy)
    })
    .compat()
    .to_boxed()
  }
}

fn extract_stderr(
  store: &Store,
  execute_response: &bazel_protos::remote_execution::ExecuteResponse,
) -> BoxFuture<Bytes, String> {
  if execute_response.get_result().has_stderr_digest() {
    let store = store.clone();
    let stderr_digest_result: Result<Digest, String> =
      execute_response.get_result().get_stderr_digest().into();
    let stderr_digest =
      try_future!(stderr_digest_result.map_err(|err| format!("Error extracting stderr: {}", err)));

    Box::pin(async move {
      let (bytes, _metadata) = store
        .load_file_bytes_with(stderr_digest, |v| v)
        .map_err(move |error| {
          format!(
            "Error fetching stderr digest ({:?}): {:?}",
            stderr_digest, error
          )
        })
        .await?
        .ok_or_else(|| {
          format!(
            "Couldn't find stderr digest ({:?}), when fetching.",
            stderr_digest
          )
        })?;
      Ok(bytes)
    })
    .compat()
    .to_boxed()
  } else {
    let store = store.clone();
    let stderr_raw = Bytes::from(execute_response.get_result().get_stderr_raw());
    let stderr_copy = stderr_raw.clone();
    Box::pin(async move {
      store
        .store_file_bytes(stderr_raw, true)
        .map_err(move |error| format!("Error storing raw stderr: {:?}", error))
        .await?;
      Ok(stderr_copy)
    })
    .compat()
    .to_boxed()
  }
}

pub fn extract_output_files(
  store: Store,
  execute_response: &bazel_protos::remote_execution::ExecuteResponse,
) -> BoxFuture<Digest, String> {
  // Get Digests of output Directories.
  // Then we'll make a Directory for the output files, and merge them.
  let mut directory_digests =
    Vec::with_capacity(execute_response.get_result().get_output_directories().len() + 1);
  // TODO: Maybe take rather than clone
  let output_directories = execute_response
    .get_result()
    .get_output_directories()
    .to_owned();
  for dir in output_directories {
    let store = store.clone();
    directory_digests.push(
      (async move {
        let digest_result: Result<Digest, String> = dir.get_tree_digest().into();
        let mut digest = digest_result?;
        if !dir.get_path().is_empty() {
          for component in dir.get_path().rsplit('/') {
            let component = component.to_owned();
            let mut directory = bazel_protos::remote_execution::Directory::new();
            directory.mut_directories().push({
              let mut node = bazel_protos::remote_execution::DirectoryNode::new();
              node.set_name(component);
              node.set_digest((&digest).into());
              node
            });
            digest = store.record_directory(&directory, true).await?;
          }
        }
        let res: Result<_, String> = Ok(digest);
        res
      })
      .map_err(|err| format!("Error saving remote output directory: {}", err)),
    );
  }

  // Make a directory for the files
  let mut path_map = HashMap::new();
  let path_stats_result: Result<Vec<PathStat>, String> = execute_response
    .get_result()
    .get_output_files()
    .iter()
    .map(|output_file| {
      let output_file_path_buf = PathBuf::from(output_file.get_path());
      let digest: Result<Digest, String> = output_file.get_digest().into();
      path_map.insert(output_file_path_buf.clone(), digest?);
      Ok(PathStat::file(
        output_file_path_buf.clone(),
        File {
          path: output_file_path_buf,
          is_executable: output_file.get_is_executable(),
        },
      ))
    })
    .collect();

  let path_stats = try_future!(path_stats_result);

  #[derive(Clone)]
  struct StoreOneOffRemoteDigest {
    map_of_paths_to_digests: HashMap<PathBuf, Digest>,
  }

  impl StoreOneOffRemoteDigest {
    fn new(map: HashMap<PathBuf, Digest>) -> StoreOneOffRemoteDigest {
      StoreOneOffRemoteDigest {
        map_of_paths_to_digests: map,
      }
    }
  }

  impl StoreFileByDigest<String> for StoreOneOffRemoteDigest {
    fn store_by_digest(&self, file: File) -> BoxFuture<Digest, String> {
      match self.map_of_paths_to_digests.get(&file.path) {
        Some(digest) => future::ok(*digest),
        None => future::err(format!(
          "Didn't know digest for path in remote execution response: {:?}",
          file.path
        )),
      }
      .to_boxed()
    }
  }

  Box::pin(async move {
    let files_digest = Snapshot::digest_from_path_stats(
      store.clone(),
      StoreOneOffRemoteDigest::new(path_map),
      &path_stats,
    )
    .map_err(move |error| {
      format!(
        "Error when storing the output file directory info in the remote CAS: {:?}",
        error
      )
    });

    let (files_digest, mut directory_digests) =
      future03::try_join(files_digest, future03::try_join_all(directory_digests)).await?;

    directory_digests.push(files_digest);
    Snapshot::merge_directories(store, directory_digests)
      .map_err(|err| format!("Error when merging output files and directories: {}", err))
      .await
  })
  .compat()
  .to_boxed()
}

pub fn format_error(error: &bazel_protos::status::Status) -> String {
  let error_code_enum = bazel_protos::code::Code::from_i32(error.get_code());
  let error_code = match error_code_enum {
    Some(x) => format!("{:?}", x),
    None => format!("{:?}", error.get_code()),
  };
  format!("{}: {}", error_code, error.get_message())
}

///
/// If the given operation represents a cancelled request, recover it into
/// ExecutionError::NotFinished.
///
fn rpcerror_recover_cancelled(
  operation_name: String,
  err: grpcio::Error,
) -> Result<bazel_protos::operations::Operation, grpcio::Error> {
  // If the error represented cancellation, return an Operation for the given Operation name.
  match &err {
    &grpcio::Error::RpcFailure(ref rs) if rs.status == grpcio::RpcStatusCode::CANCELLED => {
      let mut next_operation = bazel_protos::operations::Operation::new();
      next_operation.set_name(operation_name);
      return Ok(next_operation);
    }
    _ => {}
  }
  // Did not represent cancellation.
  Err(err)
}

fn rpcerror_to_status_or_string(
  error: grpcio::Error,
) -> Result<bazel_protos::status::Status, String> {
  match error {
    grpcio::Error::RpcFailure(grpcio::RpcStatus {
      status_proto_bytes: Some(status_proto_bytes),
      ..
    }) => {
      let mut status_proto = bazel_protos::status::Status::new();
      status_proto.merge_from_bytes(&status_proto_bytes).unwrap();
      Ok(status_proto)
    }
    grpcio::Error::RpcFailure(grpcio::RpcStatus {
      status, details, ..
    }) => Err(format!(
      "{:?}: {:?}",
      status,
      details.unwrap_or_else(|| "[no message]".to_string())
    )),
    err => Err(format!("{:?}", err)),
  }
}

fn rpcerror_to_string(error: grpcio::Error) -> String {
  match error {
    grpcio::Error::RpcFailure(status) => format!(
      "{:?}: {:?}",
      status.status,
      status.details.unwrap_or_else(|| "[no message]".to_string())
    ),
    err => format!("{:?}", err),
  }
}

pub fn digest(message: &dyn Message) -> Result<Digest, String> {
  let bytes = message.write_to_bytes().map_err(|e| format!("{:?}", e))?;

  let mut hasher = Sha256::default();
  hasher.input(&bytes);

  Ok(Digest(
    Fingerprint::from_bytes_unsafe(&hasher.fixed_result()),
    bytes.len(),
  ))
}
