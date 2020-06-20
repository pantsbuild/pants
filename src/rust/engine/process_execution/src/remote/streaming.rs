use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use bazel_protos::call_option;
use bazel_protos::error_details::PreconditionFailure;
use bazel_protos::remote_execution::{
  Action, Command, ExecuteRequest, ExecuteResponse, ExecutedActionMetadata, WaitExecutionRequest,
};
use bazel_protos::status::Status;
use bytes::Bytes;
use concrete_time::TimeSpan;
use futures::compat::{Future01CompatExt, Stream01CompatExt};
use futures::future::{self as future03};
use futures::{Stream, StreamExt};
use hashing::{Digest, Fingerprint};
use log::{debug, trace, warn, Level};
use protobuf::Message;
use store::Store;

use super::{
  format_error, maybe_add_workunit, populate_fallible_execution_result,
  populate_fallible_execution_result_for_timeout, ExecutionError, OperationOrStatus,
};
use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, Platform, PlatformConstraint,
  Process, ProcessMetadata,
};
use workunit_store::{with_workunit, WorkunitMetadata};

/// Implementation of CommandRunner that runs a command via the Bazel Remote Execution API
/// (https://docs.google.com/document/d/1AaGk7fOPByEvpAbqeXIyE8HX_A3_axxNnvroblTZ_6s/edit).
///
/// Results are streamed from the output stream of the Execute function (and possibly the
/// WaitExecution function if `StreamingCommandRunner` needs to reconnect).
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
#[derive(Clone)]
pub struct StreamingCommandRunner {
  metadata: ProcessMetadata,
  platform: Platform,
  store: Store,
  headers: BTreeMap<String, String>,
  channel: grpcio::Channel,
  env: Arc<grpcio::Environment>,
  execution_client: Arc<bazel_protos::remote_execution_grpc::ExecutionClient>,
  overall_deadline: Duration,
}

enum StreamOutcome {
  Complete(OperationOrStatus),
  StreamClosed(Option<String>),
}

impl StreamingCommandRunner {
  /// Construct a new StreamingCommandRunner
  pub fn new(
    address: &str,
    metadata: ProcessMetadata,
    root_ca_certs: Option<Vec<u8>>,
    oauth_bearer_token: Option<String>,
    headers: BTreeMap<String, String>,
    store: Store,
    platform: Platform,
    overall_deadline: Duration,
  ) -> Result<Self, String> {
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

    let mut headers = headers;
    if let Some(oauth_bearer_token) = oauth_bearer_token {
      headers.insert(
        String::from("authorization"),
        format!("Bearer {}", oauth_bearer_token),
      );
    }

    // Validate that any configured static headers are valid.
    call_option(&headers, None)?;

    let command_runner = StreamingCommandRunner {
      metadata,
      headers,
      channel,
      env,
      execution_client,
      store,
      platform,
      overall_deadline,
    };

    Ok(command_runner)
  }

  pub fn platform(&self) -> Platform {
    self.platform
  }

  async fn store_proto_locally<P: protobuf::Message>(&self, proto: &P) -> Result<Digest, String> {
    let command_bytes = proto
      .write_to_bytes()
      .map_err(|e| format!("Error serializing proto {:?}", e))?;
    self
      .store
      .store_file_bytes(Bytes::from(command_bytes), true)
      .await
      .map_err(|e| format!("Error saving proto to local store: {:?}", e))
  }

  async fn ensure_action_uploaded(
    &self,
    store: &Store,
    command: &Command,
    action: &Action,
    input_files: Digest,
  ) -> Result<(), String> {
    let (command_digest, action_digest) = future03::try_join(
      self.store_proto_locally(command),
      self.store_proto_locally(action),
    )
    .await?;

    let _ = store
      .ensure_remote_has_recursive(vec![command_digest, action_digest, input_files])
      .compat()
      .await?;

    Ok(())
  }

  // Monitors the operation stream returned by the REv2 Execute and WaitExecution methods.
  // Outputs progress reported by the server and returns the next actionable operation
  // or gRPC status back to the main loop (plus the operation name so the main loop can
  // reconnect).
  async fn wait_on_operation_stream<S>(&self, mut stream: S, build_id: &str) -> StreamOutcome
  where
    S: Stream<Item = Result<bazel_protos::operations::Operation, grpcio::Error>> + Unpin,
  {
    let mut operation_name_opt: Option<String> = None;

    trace!(
      "wait_on_operation_stream (build_id={}): monitoring stream",
      build_id
    );

    loop {
      match stream.next().await {
        Some(Ok(operation)) => {
          trace!(
            "wait_on_operation_stream (build_id={}): got operation: {:?}",
            build_id,
            &operation
          );

          // Extract the operation name.
          // Note: protobuf can return empty string for an empty field so convert empty strings
          // to None.
          operation_name_opt =
            Some(operation.get_name().to_string()).filter(|s| !s.trim().is_empty());

          // Continue monitoring if the operation is not complete.
          if !operation.get_done() {
            continue;
          }

          // Otherwise, return to the main loop with the operation as the result.
          return StreamOutcome::Complete(OperationOrStatus::Operation(operation));
        }

        Some(Err(err)) => {
          debug!("wait_on_operation_stream: got error: {:?}", err);
          match super::rpcerror_to_status_or_string(&err) {
            Ok(status) => return StreamOutcome::Complete(OperationOrStatus::Status(status)),
            Err(message) => {
              let code = match err {
                grpcio::Error::RpcFailure(rpc_status) => rpc_status.status,
                _ => grpcio::RpcStatusCode::UNKNOWN,
              };
              let mut status = bazel_protos::status::Status::new();
              status.set_code(code.into());
              status.set_message(format!("gRPC error: {}", message));
              return StreamOutcome::Complete(OperationOrStatus::Status(status));
            }
          }
        }

        None => {
          // Stream disconnected unexpectedly.
          debug!("wait_on_operation_stream: unexpected disconnect from RE server");
          return StreamOutcome::StreamClosed(operation_name_opt);
        }
      }
    }
  }

  // Store the remote timings into the workunit store.
  fn save_workunit_timings(
    &self,
    execute_response: &ExecuteResponse,
    metadata: &ExecutedActionMetadata,
  ) {
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
  }

  fn extract_missing_digests(&self, precondition_failure: &PreconditionFailure) -> ExecutionError {
    let mut missing_digests = Vec::with_capacity(precondition_failure.get_violations().len());

    for violation in precondition_failure.get_violations() {
      if violation.get_field_type() != "MISSING" {
        return ExecutionError::Fatal(format!(
          "Unknown PreconditionFailure violation: {:?}",
          violation
        ));
      }

      let parts: Vec<_> = violation.get_subject().split('/').collect();
      if parts.len() != 3 || parts[0] != "blobs" {
        return ExecutionError::Fatal(format!(
          "Received FailedPrecondition MISSING but didn't recognize subject {}",
          violation.get_subject()
        ));
      }

      let fingerprint = match Fingerprint::from_hex_string(parts[1]) {
        Ok(f) => f,
        Err(e) => {
          return ExecutionError::Fatal(format!("Bad digest in missing blob: {}: {}", parts[1], e))
        }
      };

      let size = match parts[2].parse::<usize>() {
        Ok(s) => s,
        Err(e) => {
          return ExecutionError::Fatal(format!("Missing blob had bad size: {}: {}", parts[2], e))
        }
      };

      missing_digests.push(Digest(fingerprint, size));
    }

    if missing_digests.is_empty() {
      return ExecutionError::Fatal(
        "Error from remote execution: FailedPrecondition, but no details".to_owned(),
      );
    }

    ExecutionError::MissingDigests(missing_digests)
  }

  // pub(crate) for testing
  pub(crate) async fn extract_execute_response(
    &self,
    operation_or_status: OperationOrStatus,
  ) -> Result<FallibleProcessResultWithPlatform, ExecutionError> {
    trace!("Got operation response: {:?}", operation_or_status);

    let status = match operation_or_status {
      OperationOrStatus::Operation(operation) => {
        assert!(operation.get_done(), "operation was not marked done");
        if operation.has_error() {
          warn!("protocol violation: REv2 prohibits setting Operation::error");
          return Err(ExecutionError::Fatal(format_error(&operation.get_error())));
        }

        if !operation.has_response() {
          return Err(ExecutionError::Fatal(
            "Operation finished but no response supplied".to_string(),
          ));
        }

        let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
        execute_response
          .merge_from_bytes(operation.get_response().get_value())
          .map_err(|e| ExecutionError::Fatal(format!("Invalid ExecuteResponse: {:?}", e)))?;

        debug!("Got (nested) execute response: {:?}", execute_response);

        if execute_response.get_result().has_execution_metadata() {
          let metadata = execute_response.get_result().get_execution_metadata();
          self.save_workunit_timings(&execute_response, &metadata);
        }

        let status = execute_response.take_status();
        if grpcio::RpcStatusCode::from(status.get_code()) == grpcio::RpcStatusCode::OK {
          return Ok(
            populate_fallible_execution_result(
              self.store.clone(),
              execute_response,
              vec![],
              self.platform,
            )
            .compat()
            .await
            .map_err(ExecutionError::Fatal)?,
          );
        }

        status
      }
      OperationOrStatus::Status(status) => status,
    };

    match grpcio::RpcStatusCode::from(status.get_code()) {
      grpcio::RpcStatusCode::OK => unreachable!(),

      grpcio::RpcStatusCode::DEADLINE_EXCEEDED => Err(ExecutionError::Timeout),

      grpcio::RpcStatusCode::FAILED_PRECONDITION => {
        let details = match status.get_details() {
          [] => return Err(ExecutionError::Fatal(status.get_message().to_owned())),
          [details] => details,
          _ => {
            return Err(ExecutionError::Fatal(format!(
              "Received multiple failure details in ExecuteResponse's status field: {:?}",
              status.get_details()
            )))
          }
        };

        let mut precondition_failure = PreconditionFailure::new();
        let full_name = format!(
          "type.googleapis.com/{}",
          precondition_failure.descriptor().full_name()
        );
        if details.get_type_url() != full_name {
          return Err(ExecutionError::Fatal(format!(
            "Received PreconditionFailure, but didn't know how to resolve it: {}, protobuf type {}",
            status.get_message(),
            details.get_type_url()
          )));
        }

        // Decode the precondition failure.
        precondition_failure
          .merge_from_bytes(details.get_value())
          .map_err(|e| {
            ExecutionError::Fatal(format!(
              "Error deserializing PreconditionFailure proto: {:?}",
              e
            ))
          })?;

        Err(self.extract_missing_digests(&precondition_failure))
      }

      grpcio::RpcStatusCode::ABORTED
      | grpcio::RpcStatusCode::INTERNAL
      | grpcio::RpcStatusCode::RESOURCE_EXHAUSTED
      | grpcio::RpcStatusCode::UNAVAILABLE
      | grpcio::RpcStatusCode::UNKNOWN => {
        Err(ExecutionError::Retryable(status.get_message().to_owned()))
      }
      code => Err(ExecutionError::Fatal(format!(
        "Error from remote execution: {:?}: {:?}",
        code,
        status.get_message()
      ))),
    }
  }

  // Main loop: This function connects to the RE server and submits the given remote execution
  // request via the REv2 Execute method. It then monitors the operation stream until the
  // request completes. It will reconnect using the REv2 WaitExecution method if the connection
  // is dropped.
  //
  // The `run` method on CommandRunner uses this function to implement the bulk of the
  // processing for remote execution requests. The `run` method wraps the call with the method
  // with an overall deadline timeout.
  async fn run_execute_request(
    &self,
    execute_request: ExecuteRequest,
    process: Process,
    context: &Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    let start_time = Instant::now();
    let mut current_operation_name: Option<String> = None;

    loop {
      let call_opt = call_option(&self.headers, Some(context.build_id.clone()))?;
      let rpc_result = match current_operation_name {
        None => {
          // The request has not been submitted yet. Submit the request using the REv2
          // Execute method.
          trace!(
            "no current operation: submitting execute request: build_id={}; execute_request={:?}",
            context.build_id,
            execute_request
          );
          self
            .execution_client
            .execute_opt(&execute_request, call_opt)
        }

        Some(ref operation_name) => {
          // The request has been submitted already. Reconnect to the status stream
          // using the REv2 WaitExecution method.
          trace!(
            "existing operation: reconnecting to operation stream: build_id={}; operation_name={}",
            context.build_id,
            operation_name
          );
          let mut wait_execution_request = WaitExecutionRequest::new();
          wait_execution_request.set_name(operation_name.to_owned());
          self
            .execution_client
            .wait_execution_opt(&wait_execution_request, call_opt)
        }
      };

      // Take action based on whether we received an output stream or whether there is an
      // error to resolve.
      let actionable_result = match rpc_result {
        Ok(operation_stream) => {
          // Monitor the operation stream until there is an actionable operation
          // or status to interpret.
          let compat_stream = operation_stream.compat();
          let stream_outcome = self
            .wait_on_operation_stream(compat_stream, &context.build_id)
            .await;

          match stream_outcome {
            StreamOutcome::Complete(status) => {
              trace!(
                "wait_on_operation_stream (build_id={}) returned completion={:?}",
                context.build_id,
                status
              );
              status
            }
            StreamOutcome::StreamClosed(operation_name_opt) => {
              trace!("wait_on_operation_stream (build_id={}) returned stream close, will retry operation_name={:?}", context.build_id, operation_name_opt);
              current_operation_name = operation_name_opt;
              continue;
            }
          }
        }
        Err(err) => match err {
          grpcio::Error::RpcFailure(rpc_status) => {
            let mut status = Status::new();
            status.code = rpc_status.status.into();
            OperationOrStatus::Status(status)
          }
          _ => {
            return Err(format!("gRPC error: {}", err));
          }
        },
      };

      match self.extract_execute_response(actionable_result).await {
        Ok(result) => return Ok(result),
        Err(err) => match err {
          ExecutionError::Fatal(e) => return Err(e),
          ExecutionError::Retryable(e) => {
            // do nothing, will retry
            trace!("retryable error: {}", e);
          }
          ExecutionError::MissingDigests(missing_digests) => {
            trace!(
              "Server reported missing digests; trying to upload: {:?}",
              missing_digests,
            );

            let _ = self
              .store
              .ensure_remote_has_recursive(missing_digests)
              .compat()
              .await?;
          }
          ExecutionError::NotFinished(_) => unreachable!(),
          ExecutionError::Timeout => {
            return populate_fallible_execution_result_for_timeout(
              &self.store,
              &process.description,
              process.timeout,
              start_time.elapsed(),
              Vec::new(),
              self.platform,
            )
            .await
          }
        },
      }
    }
  }
}

#[async_trait]
impl crate::CommandRunner for StreamingCommandRunner {
  /// Run the given MultiPlatformProcess via the Remote Execution API.
  async fn run(
    &self,
    request: MultiPlatformProcess,
    context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    // Construct the REv2 ExecuteRequest and related data for this execution request.
    let request = self.extract_compatible_request(&request).unwrap();
    let store = self.store.clone();
    let (action, command, execute_request) =
      super::make_execute_request(&request, self.metadata.clone())?;
    let build_id = context.build_id.clone();

    debug!("Remote execution: {}", request.description);
    trace!(
      "built REv2 request (build_id={}): action={:?}; command={:?}; execute_request={:?}",
      &build_id,
      action,
      command,
      execute_request
    );

    // Record the time that we started to process this request, then compute the ultimate
    // deadline for execution of this request.
    let deadline_duration = self.overall_deadline + request.timeout.unwrap_or_default();

    // Upload the action (and related data, i.e. the embedded command and input files).
    with_workunit(
      context.workunit_store.clone(),
      "ensure_action_uploaded".to_owned(),
      WorkunitMetadata::with_level(Level::Debug),
      self.ensure_action_uploaded(&store, &command, &action, request.input_files),
      |_, md| md,
    )
    .await?;

    // Submit the execution request to the RE server for execution.
    let result_fut = self.run_execute_request(execute_request, request, &context);
    let timeout_fut = tokio::time::timeout(deadline_duration, result_fut);
    let response = with_workunit(
      context.workunit_store.clone(),
      "run_execute_request".to_owned(),
      WorkunitMetadata::with_level(Level::Debug),
      timeout_fut,
      |result, mut metadata| {
        if result.is_err() {
          metadata.level = Level::Error;
          metadata.desc = Some(format!(
            "remote execution timed out after {:?}",
            deadline_duration
          ));
        }
        metadata
      },
    )
    .await;
    match response {
      Ok(r) => r,
      Err(_) => {
        debug!(
          "remote execution for build_id={} timed out after {:?}",
          &build_id, deadline_duration
        );
        Err(format!(
          "remote execution timed out after {:?}",
          deadline_duration
        ))
      }
    }
  }

  // TODO: This is a copy of the same method on crate::remote::CommandRunner.
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
}
