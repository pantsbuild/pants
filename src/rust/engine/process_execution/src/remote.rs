use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap};
use std::convert::TryInto;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use bazel_protos::call_option;
use bazel_protos::error_details::PreconditionFailure;
use bazel_protos::remote_execution::{
  Action, Command, ExecuteRequest, ExecuteResponse, ExecutedActionMetadata, WaitExecutionRequest,
};
use bazel_protos::status::Status;
use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use concrete_time::TimeSpan;
use double_checked_cell_async::DoubleCheckedCell;
use fs::{self, File, PathStat};
use futures::compat::{Future01CompatExt, Stream01CompatExt};
use futures::future::{self, TryFutureExt};
use futures::{Stream, StreamExt};
use futures01::Future as Future01;
use hashing::{Digest, Fingerprint};
use log::{debug, trace, warn, Level};
use protobuf::{self, Message, ProtobufEnum};
use store::{Snapshot, SnapshotOps, Store, StoreFileByDigest};
use workunit_store::{with_workunit, WorkunitMetadata, WorkunitStore};

use crate::{
  Context, ExecutionStats, FallibleProcessResultWithPlatform, MultiPlatformProcess, Platform,
  PlatformConstraint, Process, ProcessMetadata,
};

// Environment variable which is exclusively used for cache key invalidation.
// This may be not specified in an Process, and may be populated only by the
// CommandRunner.
pub const CACHE_KEY_GEN_VERSION_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_GEN_VERSION";

#[derive(Debug)]
pub enum OperationOrStatus {
  Operation(bazel_protos::operations::Operation),
  Status(bazel_protos::status::Status),
}

#[derive(Debug, PartialEq)]
pub enum ExecutionError {
  // String is the error message.
  Fatal(String),
  // Digests are Files and Directories which have been reported to be missing. May be incomplete.
  MissingDigests(Vec<Digest>),
  // The server indicated that the request hit a timeout. Generally this is the timeout that the
  // client has pushed down on the ExecutionRequest.
  Timeout,
  // String is the error message.
  Retryable(String),
}

/// Implementation of CommandRunner that runs a command via the Bazel Remote Execution API
/// (https://docs.google.com/document/d/1AaGk7fOPByEvpAbqeXIyE8HX_A3_axxNnvroblTZ_6s/edit).
///
/// Results are streamed from the output stream of the Execute function (and possibly the
/// WaitExecution function if `CommandRunner` needs to reconnect).
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
pub struct CommandRunner {
  metadata: ProcessMetadata,
  platform: Platform,
  store: Store,
  headers: BTreeMap<String, String>,
  channel: grpcio::Channel,
  env: Arc<grpcio::Environment>,
  execution_client: Arc<bazel_protos::remote_execution_grpc::ExecutionClient>,
  action_cache_client: Arc<bazel_protos::remote_execution_grpc::ActionCacheClient>,
  overall_deadline: Duration,
  capabilities_cell: Arc<DoubleCheckedCell<bazel_protos::remote_execution::ServerCapabilities>>,
  capabilities_client: Arc<bazel_protos::remote_execution_grpc::CapabilitiesClient>,
}

enum StreamOutcome {
  Complete(OperationOrStatus),
  StreamClosed(Option<String>),
}

impl CommandRunner {
  /// Construct a new CommandRunner
  pub fn new(
    address: &str,
    store_servers: Vec<String>,
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
      if let Some(ref root_ca_certs) = root_ca_certs {
        let creds = grpcio::ChannelCredentialsBuilder::new()
          .root_cert(root_ca_certs.clone())
          .build();
        builder.secure_connect(address, creds)
      } else {
        builder.connect(address)
      }
    };
    let execution_client = Arc::new(bazel_protos::remote_execution_grpc::ExecutionClient::new(
      channel.clone(),
    ));

    let store_channel = {
      let store_server = store_servers
        .get(0)
        .ok_or_else(|| "At least one store_server must be specified".to_owned())?;
      let builder = grpcio::ChannelBuilder::new(env.clone());
      if let Some(ref root_ca_certs) = root_ca_certs {
        let creds = grpcio::ChannelCredentialsBuilder::new()
          .root_cert(root_ca_certs.clone())
          .build();
        builder.secure_connect(&store_server, creds)
      } else {
        builder.connect(&store_server)
      }
    };
    let action_cache_client = Arc::new(
      bazel_protos::remote_execution_grpc::ActionCacheClient::new(store_channel),
    );

    let mut headers = headers;
    if let Some(oauth_bearer_token) = oauth_bearer_token {
      headers.insert(
        String::from("authorization"),
        format!("Bearer {}", oauth_bearer_token),
      );
    }

    // Validate any configured static headers.
    call_option(&headers, None)?;

    let capabilities_client =
      Arc::new(bazel_protos::remote_execution_grpc::CapabilitiesClient::new(channel.clone()));

    let command_runner = CommandRunner {
      metadata,
      headers,
      channel,
      env,
      execution_client,
      action_cache_client,
      store,
      platform,
      overall_deadline,
      capabilities_cell: Arc::new(DoubleCheckedCell::new()),
      capabilities_client,
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

  async fn get_capabilities(
    &self,
  ) -> Result<&bazel_protos::remote_execution::ServerCapabilities, String> {
    let capabilities_fut = async {
      let opt = call_option(&self.headers, None)?;
      let mut request = bazel_protos::remote_execution::GetCapabilitiesRequest::new();
      if let Some(s) = self.metadata.instance_name.as_ref() {
        request.instance_name = s.clone();
      }
      self
        .capabilities_client
        .get_capabilities_async_opt(&request, opt)
        .unwrap()
        .compat()
        .await
        .map_err(rpcerror_to_string)
    };

    self
      .capabilities_cell
      .get_or_try_init(capabilities_fut)
      .await
  }

  /// Check the remote Action Cache for a cached result of running the given `action_digest`.
  ///
  /// This check is necessary because some RE servers do not short-circuit the Execute method
  /// by checking the Action Cache (e.g., BuildBarn). Thus, this client must check the cache
  /// explicitly in order to avoid duplicating already-cached work. This behavior matches
  /// the Bazel RE client.
  async fn check_action_cache(
    &self,
    action_digest: Digest,
    metadata: &ProcessMetadata,
    context: &Context,
  ) -> Result<Option<FallibleProcessResultWithPlatform>, String> {
    let mut request = bazel_protos::remote_execution::GetActionResultRequest::new();
    if let Some(ref instance_name) = metadata.instance_name {
      request.set_instance_name(instance_name.clone());
    }
    request.set_action_digest(action_digest.into());

    let call_opt = call_option(&self.headers, Some(context.build_id.clone()))?;

    let action_result_response = self
      .action_cache_client
      .get_action_result_async_opt(&request, call_opt)
      .unwrap()
      .compat()
      .await;

    match action_result_response {
      Ok(action_result) => {
        let response = populate_fallible_execution_result(
          self.store.clone(),
          &action_result,
          vec![],
          self.platform,
        )
        .compat()
        .await?;
        Ok(Some(response))
      }
      Err(err) => match err {
        grpcio::Error::RpcFailure(rpc_status)
          if rpc_status.status == grpcio::RpcStatusCode::NOT_FOUND =>
        {
          Ok(None)
        }
        _ => Err(rpcerror_to_string(err)),
      },
    }
  }

  async fn ensure_action_stored_locally(
    &self,
    command: &Command,
    action: &Action,
  ) -> Result<(Digest, Digest), String> {
    let (command_digest, action_digest) = future::try_join(
      self.store_proto_locally(command),
      self.store_proto_locally(action),
    )
    .await?;

    Ok((command_digest, action_digest))
  }

  async fn ensure_action_uploaded(
    &self,
    store: &Store,
    command_digest: Digest,
    action_digest: Digest,
    input_files: Digest,
  ) -> Result<(), String> {
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
          match rpcerror_to_status_or_string(&err) {
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
              execute_response.get_result(),
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
impl crate::CommandRunner for CommandRunner {
  /// Run the given MultiPlatformProcess via the Remote Execution API.
  async fn run(
    &self,
    request: MultiPlatformProcess,
    context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    // Retrieve capabilities for this server.
    let capabilities = self.get_capabilities().await?;
    trace!("RE capabilities: {:?}", &capabilities);

    // Construct the REv2 ExecuteRequest and related data for this execution request.
    let request = self.extract_compatible_request(&request).unwrap();
    let store = self.store.clone();
    let (action, command, execute_request) = make_execute_request(&request, self.metadata.clone())?;
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

    // Ensure the action and command are stored locally.
    let (command_digest, action_digest) = with_workunit(
      context.workunit_store.clone(),
      "ensure_action_stored_locally".to_owned(),
      WorkunitMetadata::with_level(Level::Debug),
      self.ensure_action_stored_locally(&command, &action),
      |_, md| md,
    )
    .await?;

    // Check the remote Action Cache to see if this request was already computed.
    // If so, return immediately with the result.
    let cached_response_opt = with_workunit(
      context.workunit_store.clone(),
      "check_action_cache".to_owned(),
      WorkunitMetadata::with_level(Level::Debug),
      self.check_action_cache(action_digest, &self.metadata, &context),
      |_, md| md,
    )
    .await?;
    if let Some(cached_response) = cached_response_opt {
      return Ok(cached_response);
    }

    // Upload the action (and related data, i.e. the embedded command and input files).
    with_workunit(
      context.workunit_store.clone(),
      "ensure_action_uploaded".to_owned(),
      WorkunitMetadata::with_level(Level::Debug),
      self.ensure_action_uploaded(&store, command_digest, action_digest, request.input_files),
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

fn maybe_add_workunit(
  result_cached: bool,
  name: &str,
  time_span: concrete_time::TimeSpan,
  parent_id: Option<String>,
  workunit_store: &WorkunitStore,
) {
  if !result_cached {
    let start_time: SystemTime = SystemTime::UNIX_EPOCH + time_span.start.into();
    let end_time: SystemTime = start_time + time_span.duration.into();
    let metadata = workunit_store::WorkunitMetadata::new();
    workunit_store.add_completed_workunit(
      name.to_string(),
      start_time,
      end_time,
      parent_id,
      metadata,
    );
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

  // TODO: Disabling append-only caches in remoting until server support exists due to
  //       interaction with how servers match platform properties.
  // if !req.append_only_caches.is_empty() {
  //   platform_properties.extend(NamedCaches::platform_properties(
  //     &req.append_only_caches,
  //     &cache_key_gen_version,
  //   ));
  // }

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

  if !platform_properties
    .iter()
    .any(|(k, _)| k == "target_platform")
  {
    platform_properties.push(("target_platform".to_owned(), req.target_platform.into()));
  }

  for (name, value) in platform_properties {
    command.mut_platform().mut_properties().push({
      let mut property = bazel_protos::remote_execution::Platform_Property::new();
      property.set_name(name.clone());
      property.set_value(value.clone());
      property
    });
  }

  // Sort the platform properties.
  //
  // From the remote execution spec:
  //   The properties that make up this platform. In order to ensure that
  //   equivalent `Platform`s always hash to the same value, the properties MUST
  //   be lexicographically sorted by name, and then by value. Sorting of strings
  //   is done by code point, equivalently, by the UTF-8 bytes.
  //
  // Note: BuildBarn enforces this requirement.
  command
    .mut_platform()
    .mut_properties()
    .sort_by(|x, y| match x.name.cmp(&y.name) {
      Ordering::Equal => x.value.cmp(&y.value),
      v => v,
    });

  // Sort the environment variables. REv2 spec requires sorting by name for same reasons that
  // platform properties are sorted, i.e. consistent hashing.
  command
    .mut_environment_variables()
    .sort_by(|x, y| x.name.cmp(&y.name));

  let mut action = bazel_protos::remote_execution::Action::new();
  action.set_command_digest((&digest(&command)?).into());
  action.set_input_root_digest((&req.input_files).into());

  if let Some(timeout) = req.timeout {
    let mut timeout_duration = protobuf::well_known_types::Duration::new();
    timeout_duration.set_seconds(timeout.as_secs() as i64);
    timeout_duration.set_nanos(timeout.subsec_nanos() as i32);
    action.set_timeout(timeout_duration);
  }

  let mut execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  if let Some(instance_name) = instance_name {
    execute_request.set_instance_name(instance_name);
  }
  execute_request.set_action_digest((&digest(&action)?).into());

  Ok((action, command, execute_request))
}

pub async fn populate_fallible_execution_result_for_timeout(
  store: &Store,
  description: &str,
  timeout: Option<Duration>,
  elapsed: Duration,
  execution_attempts: Vec<ExecutionStats>,
  platform: Platform,
) -> Result<FallibleProcessResultWithPlatform, String> {
  let timeout_msg = if let Some(timeout) = timeout {
    format!("user timeout of {:?} after {:?}", timeout, elapsed)
  } else {
    format!("server timeout after {:?}", elapsed)
  };
  let stdout = Bytes::from(format!("Exceeded {} for {}", timeout_msg, description));
  let stdout_digest = store.store_file_bytes(stdout, true).await?;

  Ok(FallibleProcessResultWithPlatform {
    stdout_digest,
    stderr_digest: hashing::EMPTY_DIGEST,
    exit_code: -libc::SIGTERM,
    output_directory: hashing::EMPTY_DIGEST,
    execution_attempts,
    platform,
  })
}

pub fn populate_fallible_execution_result(
  store: Store,
  action_result: &bazel_protos::remote_execution::ActionResult,
  execution_attempts: Vec<ExecutionStats>,
  platform: Platform,
) -> impl Future01<Item = FallibleProcessResultWithPlatform, Error = String> {
  let exit_code = action_result.get_exit_code();
  extract_stdout(&store, action_result)
    .join(extract_stderr(&store, action_result))
    .join(extract_output_files(store, action_result))
    .and_then(move |((stdout_digest, stderr_digest), output_directory)| {
      Ok(FallibleProcessResultWithPlatform {
        stdout_digest,
        stderr_digest,
        exit_code,
        output_directory,
        execution_attempts,
        platform,
      })
    })
    .to_boxed()
}

fn extract_stdout(
  store: &Store,
  action_result: &bazel_protos::remote_execution::ActionResult,
) -> BoxFuture<Digest, String> {
  if action_result.has_stdout_digest() {
    let stdout_digest_result: Result<Digest, String> = action_result.get_stdout_digest().try_into();
    let stdout_digest =
      try_future!(stdout_digest_result.map_err(|err| format!("Error extracting stdout: {}", err)));
    Box::pin(async move { Ok(stdout_digest) })
      .compat()
      .to_boxed()
  } else {
    let store = store.clone();
    let stdout_raw = Bytes::from(action_result.get_stdout_raw());
    Box::pin(async move {
      let digest = store
        .store_file_bytes(stdout_raw, true)
        .map_err(move |error| format!("Error storing raw stdout: {:?}", error))
        .await?;
      Ok(digest)
    })
    .compat()
    .to_boxed()
  }
}

fn extract_stderr(
  store: &Store,
  action_result: &bazel_protos::remote_execution::ActionResult,
) -> BoxFuture<Digest, String> {
  if action_result.has_stderr_digest() {
    let stderr_digest_result: Result<Digest, String> = action_result.get_stderr_digest().try_into();
    let stderr_digest =
      try_future!(stderr_digest_result.map_err(|err| format!("Error extracting stderr: {}", err)));
    Box::pin(async move { Ok(stderr_digest) })
      .compat()
      .to_boxed()
  } else {
    let store = store.clone();
    let stderr_raw = Bytes::from(action_result.get_stderr_raw());
    Box::pin(async move {
      let digest = store
        .store_file_bytes(stderr_raw, true)
        .map_err(move |error| format!("Error storing raw stderr: {:?}", error))
        .await?;
      Ok(digest)
    })
    .compat()
    .to_boxed()
  }
}

pub fn extract_output_files(
  store: Store,
  action_result: &bazel_protos::remote_execution::ActionResult,
) -> BoxFuture<Digest, String> {
  // Get Digests of output Directories.
  // Then we'll make a Directory for the output files, and merge them.
  let mut directory_digests = Vec::with_capacity(action_result.get_output_directories().len() + 1);
  // TODO: Maybe take rather than clone
  let output_directories = action_result.get_output_directories().to_owned();
  for dir in output_directories {
    let store = store.clone();
    directory_digests.push(
      (async move {
        let digest_result: Result<Digest, String> = dir.get_tree_digest().try_into();
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
  let path_stats_result: Result<Vec<PathStat>, String> = action_result
    .get_output_files()
    .iter()
    .map(|output_file| {
      let output_file_path_buf = PathBuf::from(output_file.get_path());
      let digest: Result<Digest, String> = output_file.get_digest().try_into();
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
      .compat()
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
      future::try_join(files_digest, future::try_join_all(directory_digests)).await?;

    directory_digests.push(files_digest);

    store
      .merge(directory_digests)
      .map_err(|err| format!("Error when merging output files and directories: {:?}", err))
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

fn rpcerror_to_status_or_string(
  error: &grpcio::Error,
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
      details
        .as_ref()
        .map(|s| s.as_str())
        .unwrap_or_else(|| "[no message]")
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
  Ok(Digest::of_bytes(&bytes))
}
