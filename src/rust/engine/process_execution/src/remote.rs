use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap};
use std::convert::TryInto;
use std::io::Cursor;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use bazel_protos::gen::google::longrunning::Operation;
use bazel_protos::gen::google::rpc::{PreconditionFailure, Status as StatusProto};
use bazel_protos::require_digest;
use bytes::Bytes;
use concrete_time::TimeSpan;
use double_checked_cell_async::DoubleCheckedCell;
use fs::{self, File, PathStat};
use futures::future::{self, BoxFuture, TryFutureExt};
use futures::FutureExt;
use futures::{Stream, StreamExt};
use grpc_util::prost::MessageExt;
use grpc_util::{headers_to_interceptor_fn, status_to_str};
use hashing::{Digest, Fingerprint};
use log::{debug, trace, warn, Level};
use prost::Message;
use rand::{thread_rng, Rng};
use remexec::{
  action_cache_client::ActionCacheClient, capabilities_client::CapabilitiesClient,
  execution_client::ExecutionClient, Action, Command, ExecuteRequest, ExecuteResponse,
  ExecutedActionMetadata, ServerCapabilities, WaitExecutionRequest,
};
use store::{Snapshot, SnapshotOps, Store, StoreFileByDigest};
use tonic::metadata::BinaryMetadataValue;
use tonic::transport::Channel;
use tonic::{Code, Interceptor, Request, Status};
use tryfuture::try_future;
use uuid::Uuid;
use workunit_store::{
  with_workunit, Metric, ObservationMetric, SpanId, WorkunitMetadata, WorkunitStore,
};

use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, Platform, Process,
  ProcessCacheScope, ProcessMetadata, ProcessResultMetadata,
};

// Environment variable which is exclusively used for cache key invalidation.
// This may be not specified in an Process, and may be populated only by the
// CommandRunner.
pub const CACHE_KEY_GEN_VERSION_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_GEN_VERSION";

// Environment variable which is used to include a unique value for cache busting of processes that
// have indicated that they should never be cached.
pub const CACHE_KEY_SALT_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_SALT";

// Environment variable which is exclusively used for cache key invalidation.
// This may be not specified in an Process, and may be populated only by the
// CommandRunner.
pub const CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_TARGET_PLATFORM";

#[derive(Debug)]
pub enum OperationOrStatus {
  Operation(Operation),
  Status(StatusProto),
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
  channel: Channel,
  execution_client: Arc<ExecutionClient<Channel>>,
  action_cache_client: Arc<ActionCacheClient<Channel>>,
  overall_deadline: Duration,
  retry_interval_duration: Duration,
  capabilities_cell: Arc<DoubleCheckedCell<ServerCapabilities>>,
  capabilities_client: Arc<CapabilitiesClient<Channel>>,
}

enum StreamOutcome {
  Complete(OperationOrStatus),
  StreamClosed(Option<String>),
}

impl CommandRunner {
  /// Construct a new CommandRunner
  pub fn new(
    execution_address: &str,
    store_address: &str,
    metadata: ProcessMetadata,
    root_ca_certs: Option<Vec<u8>>,
    headers: BTreeMap<String, String>,
    store: Store,
    platform: Platform,
    overall_deadline: Duration,
    retry_interval_duration: Duration,
  ) -> Result<Self, String> {
    let execution_use_tls = execution_address.starts_with("https://");
    let store_use_tls = store_address.starts_with("https://");

    let tls_client_config = if execution_use_tls || store_use_tls {
      Some(grpc_util::create_tls_config(root_ca_certs)?)
    } else {
      None
    };

    let interceptor = if headers.is_empty() {
      None
    } else {
      Some(Interceptor::new(headers_to_interceptor_fn(&headers)?))
    };

    let execution_endpoint = grpc_util::create_endpoint(
      &execution_address,
      tls_client_config.as_ref().filter(|_| execution_use_tls),
    )?;
    let execution_channel =
      tonic::transport::Channel::balance_list(vec![execution_endpoint].into_iter());
    let execution_client = Arc::new(match interceptor.as_ref() {
      Some(interceptor) => {
        ExecutionClient::with_interceptor(execution_channel.clone(), interceptor.clone())
      }
      None => ExecutionClient::new(execution_channel.clone()),
    });

    let store_endpoint = grpc_util::create_endpoint(
      &store_address,
      tls_client_config.as_ref().filter(|_| execution_use_tls),
    )?;
    let store_channel = tonic::transport::Channel::balance_list(vec![store_endpoint].into_iter());

    let action_cache_client = Arc::new(match interceptor.as_ref() {
      Some(interceptor) => ActionCacheClient::with_interceptor(store_channel, interceptor.clone()),
      None => ActionCacheClient::new(store_channel),
    });

    let capabilities_client = Arc::new(match interceptor.as_ref() {
      Some(interceptor) => {
        CapabilitiesClient::with_interceptor(execution_channel.clone(), interceptor.clone())
      }
      None => CapabilitiesClient::new(execution_channel.clone()),
    });

    let command_runner = CommandRunner {
      metadata,
      headers,
      channel: execution_channel,
      execution_client,
      action_cache_client,
      store,
      platform,
      overall_deadline,
      retry_interval_duration,
      capabilities_cell: Arc::new(DoubleCheckedCell::new()),
      capabilities_client,
    };

    Ok(command_runner)
  }

  pub fn platform(&self) -> Platform {
    self.platform
  }

  async fn get_capabilities(&self) -> Result<&remexec::ServerCapabilities, String> {
    let capabilities_fut = async {
      let mut request = remexec::GetCapabilitiesRequest::default();
      if let Some(s) = self.metadata.instance_name.as_ref() {
        request.instance_name = s.clone();
      }

      let request = apply_headers(Request::new(request), "");

      let mut client = self.capabilities_client.as_ref().clone();
      client
        .get_capabilities(request)
        .await
        .map(|r| r.into_inner())
        .map_err(status_to_str)
    };

    self
      .capabilities_cell
      .get_or_try_init(capabilities_fut)
      .await
  }

  // Monitors the operation stream returned by the REv2 Execute and WaitExecution methods.
  // Outputs progress reported by the server and returns the next actionable operation
  // or gRPC status back to the main loop (plus the operation name so the main loop can
  // reconnect).
  async fn wait_on_operation_stream<S>(&self, mut stream: S, context: &Context) -> StreamOutcome
  where
    S: Stream<Item = Result<Operation, Status>> + Unpin,
  {
    let mut operation_name_opt: Option<String> = None;
    let mut start_time_opt = Some(Instant::now());

    trace!(
      "wait_on_operation_stream (build_id={}): monitoring stream",
      &context.build_id
    );

    loop {
      let item = stream.next().await;

      if let Some(start_time) = start_time_opt.take() {
        let timing: Result<u64, _> = Instant::now()
          .duration_since(start_time)
          .as_micros()
          .try_into();
        if let Ok(obs) = timing {
          context
            .workunit_store
            .record_observation(ObservationMetric::RemoteExecutionRPCFirstResponseTime, obs);
        }
      }

      match item {
        Some(Ok(operation)) => {
          trace!(
            "wait_on_operation_stream (build_id={}): got operation: {:?}",
            &context.build_id,
            &operation
          );

          // Extract the operation name.
          // Note: protobuf can return empty string for an empty field so convert empty strings
          // to None.
          operation_name_opt = Some(operation.name.clone()).filter(|s| !s.trim().is_empty());

          // Continue monitoring if the operation is not complete.
          if !operation.done {
            continue;
          }

          // Otherwise, return to the main loop with the operation as the result.
          return StreamOutcome::Complete(OperationOrStatus::Operation(operation));
        }

        Some(Err(err)) => {
          debug!("wait_on_operation_stream: got error: {:?}", err);
          let status_proto = StatusProto {
            code: err.code() as i32,
            message: err.message().to_string(),
            ..StatusProto::default()
          };
          return StreamOutcome::Complete(OperationOrStatus::Status(status_proto));
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
    let workunit_thread_handle = workunit_store::expect_workunit_store_handle();
    let workunit_store = workunit_thread_handle.store;
    let parent_id = workunit_thread_handle.parent_id;
    let result_cached = execute_response.cached_result;

    if let (Some(queued_timestamp), Some(worker_start_timestamp)) = (
      metadata.queued_timestamp.as_ref(),
      metadata.worker_start_timestamp.as_ref(),
    ) {
      let span_result =
        TimeSpan::from_start_and_end(queued_timestamp, worker_start_timestamp, "remote queue");
      match span_result {
        Ok(time_span) => maybe_add_workunit(
          result_cached,
          "remote execution action scheduling",
          time_span,
          parent_id,
          &workunit_store,
          WorkunitMetadata {
            level: Level::Trace,
            ..WorkunitMetadata::default()
          },
        ),
        Err(s) => warn!("{}", s),
      }
    }

    if let (Some(input_fetch_start_timestamp), Some(input_fetch_completed_timestamp)) = (
      metadata.input_fetch_start_timestamp.as_ref(),
      metadata.input_fetch_completed_timestamp.as_ref(),
    ) {
      let span_result = TimeSpan::from_start_and_end(
        input_fetch_start_timestamp,
        input_fetch_completed_timestamp,
        "remote input fetch",
      );
      match span_result {
        Ok(time_span) => maybe_add_workunit(
          result_cached,
          "remote execution worker input fetching",
          time_span,
          parent_id,
          &workunit_store,
          WorkunitMetadata {
            level: Level::Trace,
            ..WorkunitMetadata::default()
          },
        ),
        Err(s) => warn!("{}", s),
      }
    }

    if let (Some(execution_start_timestamp), Some(execution_completed_timestamp)) = (
      metadata.execution_start_timestamp.as_ref(),
      metadata.execution_completed_timestamp.as_ref(),
    ) {
      let span_result = TimeSpan::from_start_and_end(
        execution_start_timestamp,
        execution_completed_timestamp,
        "remote execution",
      );
      match span_result {
        Ok(time_span) => maybe_add_workunit(
          result_cached,
          "remote execution worker command executing",
          time_span,
          parent_id,
          &workunit_store,
          WorkunitMetadata {
            level: Level::Trace,
            ..WorkunitMetadata::default()
          },
        ),
        Err(s) => warn!("{}", s),
      }
    }

    if let (Some(output_upload_start_timestamp), Some(output_upload_completed_timestamp)) = (
      metadata.output_upload_start_timestamp.as_ref(),
      metadata.output_upload_completed_timestamp.as_ref(),
    ) {
      let span_result = TimeSpan::from_start_and_end(
        output_upload_start_timestamp,
        output_upload_completed_timestamp,
        "remote output store",
      );
      match span_result {
        Ok(time_span) => maybe_add_workunit(
          result_cached,
          "remote execution worker output uploading",
          time_span,
          parent_id,
          &workunit_store,
          WorkunitMetadata {
            level: Level::Trace,
            ..WorkunitMetadata::default()
          },
        ),
        Err(s) => warn!("{}", s),
      }
    }
  }

  fn extract_missing_digests(&self, precondition_failure: &PreconditionFailure) -> ExecutionError {
    let mut missing_digests = Vec::with_capacity(precondition_failure.violations.len());

    for violation in &precondition_failure.violations {
      if violation.r#type != "MISSING" {
        return ExecutionError::Fatal(format!(
          "Unknown PreconditionFailure violation: {:?}",
          violation
        ));
      }

      let parts: Vec<_> = violation.subject.split('/').collect();
      if parts.len() != 3 || parts[0] != "blobs" {
        return ExecutionError::Fatal(format!(
          "Received FailedPrecondition MISSING but didn't recognize subject {}",
          violation.subject
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

      missing_digests.push(Digest::new(fingerprint, size));
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
        assert!(operation.done, "operation was not marked done");

        use bazel_protos::gen::google::longrunning::operation::Result as OperationResult;
        let execute_response = match operation.result {
          Some(OperationResult::Response(response_any)) => {
            remexec::ExecuteResponse::decode(&response_any.value[..])
              .map_err(|e| ExecutionError::Fatal(format!("Invalid ExecuteResponse: {:?}", e)))?
          }
          Some(OperationResult::Error(rpc_status)) => {
            warn!("protocol violation: REv2 prohibits setting Operation::error");
            return Err(ExecutionError::Fatal(format_error(&rpc_status)));
          }
          None => {
            return Err(ExecutionError::Fatal(
              "Operation finished but no response supplied".to_string(),
            ));
          }
        };

        debug!("Got (nested) execute response: {:?}", execute_response);

        if let Some(ref metadata) = execute_response
          .result
          .as_ref()
          .and_then(|ar| ar.execution_metadata.clone())
        {
          self.save_workunit_timings(&execute_response, metadata);
        }

        let rpc_status = execute_response.status.unwrap_or_default();
        if rpc_status.code == Code::Ok as i32 {
          let action_result = if let Some(ref action_result) = execute_response.result {
            action_result
          } else {
            warn!("REv2 protocol violation: action result not set");
            return Err(ExecutionError::Fatal(
              "REv2 protocol violation: action result not set".into(),
            ));
          };

          return populate_fallible_execution_result(
            self.store.clone(),
            action_result,
            self.platform,
            false,
          )
          .await
          .map_err(ExecutionError::Fatal);
        }

        rpc_status
      }
      OperationOrStatus::Status(status) => status,
    };

    match Code::from_i32(status.code) {
      Code::Ok => unreachable!(),

      Code::DeadlineExceeded => Err(ExecutionError::Timeout),

      Code::FailedPrecondition => {
        let details = if status.details.is_empty() {
          return Err(ExecutionError::Fatal(status.message));
        } else if status.details.len() > 1 {
          // TODO(tonic): Should we be able to handle multiple details protos?
          return Err(ExecutionError::Fatal(
            "too many detail protos for precondition failure".into(),
          ));
        } else {
          &status.details[0]
        };

        let full_name = format!("type.googleapis.com/{}", "google.rpc.PreconditionFailure");
        if details.type_url != full_name {
          return Err(ExecutionError::Fatal(format!(
            "Received PreconditionFailure, but didn't know how to resolve it: {}, protobuf type {}",
            status.message, details.type_url
          )));
        }

        // Decode the precondition failure.
        let precondition_failure = PreconditionFailure::decode(Cursor::new(&details.value))
          .map_err(|e| {
            ExecutionError::Fatal(format!(
              "Error deserializing PreconditionFailure proto: {:?}",
              e
            ))
          })?;

        Err(self.extract_missing_digests(&precondition_failure))
      }

      Code::Aborted
      | Code::Internal
      | Code::ResourceExhausted
      | Code::Unavailable
      | Code::Unknown => Err(ExecutionError::Retryable(status.message)),
      code => Err(ExecutionError::Fatal(format!(
        "Error from remote execution: {:?}: {:?}",
        code, status.message,
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
    const MAX_RETRIES: u32 = 5;
    const MAX_BACKOFF_DURATION: Duration = Duration::from_secs(10);

    let start_time = Instant::now();
    let mut current_operation_name: Option<String> = None;
    let mut num_retries = 0;

    loop {
      // If we are currently retrying a request, then delay using an exponential backoff.
      if num_retries > 0 {
        context
          .workunit_store
          .increment_counter(Metric::RemoteExecutionRPCRetries, 1);

        let multiplier = thread_rng().gen_range(0..2_u32.pow(num_retries) + 1);
        let sleep_time = self.retry_interval_duration * multiplier;
        let sleep_time = sleep_time.min(MAX_BACKOFF_DURATION);
        debug!("delaying {:?} before retry", sleep_time);
        tokio::time::sleep(sleep_time).await;
      }

      let rpc_result = match current_operation_name {
        None => {
          // The request has not been submitted yet. Submit the request using the REv2
          // Execute method.
          debug!(
            "no current operation: submitting execute request: build_id={}; execute_request={:?}",
            context.build_id, &execute_request
          );
          context
            .workunit_store
            .increment_counter(Metric::RemoteExecutionRPCExecute, 1);
          let mut client = self.execution_client.as_ref().clone();
          let request = apply_headers(Request::new(execute_request.clone()), &context.build_id);
          client.execute(request).await
        }

        Some(ref operation_name) => {
          // The request has been submitted already. Reconnect to the status stream
          // using the REv2 WaitExecution method.
          debug!(
            "existing operation: reconnecting to operation stream: build_id={}; operation_name={}",
            context.build_id, operation_name
          );
          context
            .workunit_store
            .increment_counter(Metric::RemoteExecutionRPCWaitExecution, 1);
          let wait_execution_request = WaitExecutionRequest {
            name: operation_name.to_owned(),
          };
          let mut client = self.execution_client.as_ref().clone();
          let request = apply_headers(Request::new(wait_execution_request), &context.build_id);
          client.wait_execution(request).await
        }
      };

      // Take action based on whether we received an output stream or whether there is an
      // error to resolve.
      let actionable_result = match rpc_result {
        Ok(operation_stream_response) => {
          // Monitor the operation stream until there is an actionable operation
          // or status to interpret.
          let operation_stream = operation_stream_response.into_inner();
          let stream_outcome = self
            .wait_on_operation_stream(operation_stream, &context)
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

              // Check if the number of request attempts sent thus far have exceeded the number
              // of retries allowed since the last successful connection. (There is no point in
              // continually submitting a request if ultimately futile.)
              if num_retries >= MAX_RETRIES {
                context
                  .workunit_store
                  .increment_counter(Metric::RemoteExecutionRPCErrors, 1);
                return Err(
                  "Too many failures from server. The last event was the server disconnecting with no error given.".to_owned(),
                );
              } else {
                // Increment the retry counter and allow loop to retry.
                num_retries += 1;
              }

              // Iterate the loop to reconnect to the operation.
              current_operation_name = operation_name_opt;
              continue;
            }
          }
        }
        Err(status) => {
          let status_proto = StatusProto {
            code: status.code() as i32,
            message: status.message().to_owned(),
            ..StatusProto::default()
          };
          OperationOrStatus::Status(status_proto)
        }
      };

      match self.extract_execute_response(actionable_result).await {
        Ok(result) => return Ok(result),
        Err(err) => match err {
          ExecutionError::Fatal(e) => {
            context
              .workunit_store
              .increment_counter(Metric::RemoteExecutionRPCErrors, 1);
            return Err(e);
          }
          ExecutionError::Retryable(e) => {
            // Check if the number of request attempts sent thus far have exceeded the number
            // of retries allowed since the last successful connection. (There is no point in
            // continually submitting a request if ultimately futile.)
            trace!("retryable error: {}", e);
            if num_retries >= MAX_RETRIES {
              context
                .workunit_store
                .increment_counter(Metric::RemoteExecutionRPCErrors, 1);
              return Err(format!(
                "Too many failures from server. The last error was: {}",
                e
              ));
            } else {
              // Increment the retry counter and allow loop to retry.
              num_retries += 1;
            }
          }
          ExecutionError::MissingDigests(missing_digests) => {
            trace!(
              "Server reported missing digests; trying to upload: {:?}",
              missing_digests,
            );

            let _ = self
              .store
              .ensure_remote_has_recursive(missing_digests)
              .await?;
          }
          ExecutionError::Timeout => {
            context
              .workunit_store
              .increment_counter(Metric::RemoteExecutionTimeouts, 1);
            return populate_fallible_execution_result_for_timeout(
              &self.store,
              &process.description,
              process.timeout,
              start_time.elapsed(),
              self.platform,
            )
            .await;
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
    debug!(
      "built REv2 request (build_id={}): action={:?}; command={:?}; execute_request={:?}",
      &build_id, action, command, execute_request
    );

    // Record the time that we started to process this request, then compute the ultimate
    // deadline for execution of this request.
    let deadline_duration = self.overall_deadline + request.timeout.unwrap_or_default();

    // Ensure the action and command are stored locally.
    let (command_digest, action_digest) = with_workunit(
      context.workunit_store.clone(),
      "ensure_action_stored_locally".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        desc: Some(format!("ensure action stored locally for {:?}", action)),
        ..WorkunitMetadata::default()
      },
      ensure_action_stored_locally(&self.store, &command, &action),
      |_, md| md,
    )
    .await?;

    // Check the remote Action Cache to see if this request was already computed.
    // If so, return immediately with the result.
    let cached_response_opt = with_workunit(
      context.workunit_store.clone(),
      "check_action_cache".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        desc: Some(format!("check action cache for {:?}", action_digest)),
        ..WorkunitMetadata::default()
      },
      check_action_cache(
        action_digest,
        &self.metadata,
        self.platform,
        &context,
        self.action_cache_client.clone(),
        self.store.clone(),
        false,
      ),
      |_, md| md,
    )
    .await?;
    debug!(
      "action cache response: build_id={}; digest={:?}: {:?}",
      &build_id, action_digest, cached_response_opt
    );
    if let Some(cached_response) = cached_response_opt {
      return Ok(cached_response);
    }

    // Upload the action (and related data, i.e. the embedded command and input files).
    with_workunit(
      context.workunit_store.clone(),
      "ensure_action_uploaded".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        desc: Some(format!("ensure action uploaded for {:?}", action_digest)),
        ..WorkunitMetadata::default()
      },
      ensure_action_uploaded(&store, command_digest, action_digest, request.input_files),
      |_, md| md,
    )
    .await?;

    // Submit the execution request to the RE server for execution.
    context
      .workunit_store
      .increment_counter(Metric::RemoteExecutionRequests, 1);
    let result_fut = self.run_execute_request(execute_request, request, &context);
    let timeout_fut = tokio::time::timeout(deadline_duration, result_fut);
    let response = with_workunit(
      context.workunit_store.clone(),
      "run_execute_request".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        ..WorkunitMetadata::default()
      },
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

    // Detect whether the operation ran or hit the deadline timeout.
    match response {
      Ok(result) => {
        if result.is_ok() {
          context
            .workunit_store
            .increment_counter(Metric::RemoteExecutionSuccess, 1);
        } else {
          context
            .workunit_store
            .increment_counter(Metric::RemoteExecutionErrors, 1);
        }
        result
      }
      Err(_) => {
        // The Err in this match arm originates from the timeout future.
        debug!(
          "remote execution for build_id={} timed out after {:?}",
          &build_id, deadline_duration
        );
        context
          .workunit_store
          .increment_counter(Metric::RemoteExecutionTimeouts, 1);
        Err(format!(
          "remote execution timed out after {:?}",
          deadline_duration
        ))
      }
    }
  }

  // TODO: This is a copy of the same method on crate::remote::CommandRunner.
  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    for compatible_constraint in vec![None, self.platform.into()].iter() {
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
  parent_id: Option<SpanId>,
  workunit_store: &WorkunitStore,
  metadata: WorkunitMetadata,
) {
  if !result_cached {
    let start_time: SystemTime = SystemTime::UNIX_EPOCH + time_span.start.into();
    let end_time: SystemTime = start_time + time_span.duration.into();
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
) -> Result<(remexec::Action, remexec::Command, remexec::ExecuteRequest), String> {
  let mut command = remexec::Command {
    arguments: req.argv.clone(),
    ..remexec::Command::default()
  };
  for (name, value) in &req.env {
    if name == CACHE_KEY_GEN_VERSION_ENV_VAR_NAME
      || name == CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME
      || name == CACHE_KEY_SALT_ENV_VAR_NAME
    {
      return Err(format!(
        "Cannot set env var with name {} as that is reserved for internal use by pants",
        name
      ));
    }

    command
      .environment_variables
      .push(remexec::command::EnvironmentVariable {
        name: name.to_string(),
        value: value.to_string(),
      });
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
    command
      .environment_variables
      .push(remexec::command::EnvironmentVariable {
        name: CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_string(),
        value: cache_key_gen_version,
      });
  }

  if matches!(
    req.cache_scope,
    ProcessCacheScope::PerSession
      | ProcessCacheScope::PerRestartAlways
      | ProcessCacheScope::PerRestartSuccessful
  ) {
    command
      .environment_variables
      .push(remexec::command::EnvironmentVariable {
        name: CACHE_KEY_SALT_ENV_VAR_NAME.to_string(),
        value: Uuid::new_v4().to_string(),
      });
  }

  {
    command
      .environment_variables
      .push(remexec::command::EnvironmentVariable {
        name: CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_string(),
        value: match req.platform_constraint {
          Some(plat) => plat.into(),
          None => "none".to_string(),
        },
      });
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
  command.output_files = output_files;

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
  command.output_directories = output_directories;

  if let Some(working_directory) = &req.working_directory {
    command.working_directory = working_directory
      .to_str()
      .map(str::to_owned)
      .unwrap_or_else(|| panic!("Non-UTF8 working directory path: {:?}", working_directory));
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

  // Extract `Platform` proto from the `Command` to avoid a partial move of `Command`.
  let mut command_platform = command.platform.take().unwrap_or_default();

  // Add configured platform properties to the `Platform`.
  for (name, value) in platform_properties {
    command_platform
      .properties
      .push(remexec::platform::Property {
        name: name.clone(),
        value: value.clone(),
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
  command_platform
    .properties
    .sort_by(|x, y| match x.name.cmp(&y.name) {
      Ordering::Equal => x.value.cmp(&y.value),
      v => v,
    });

  // Store the separate copy back into the Command proto.
  command.platform = Some(command_platform);

  // Sort the environment variables. REv2 spec requires sorting by name for same reasons that
  // platform properties are sorted, i.e. consistent hashing.
  command
    .environment_variables
    .sort_by(|x, y| x.name.cmp(&y.name));

  let mut action = remexec::Action {
    command_digest: Some((&digest(&command)?).into()),
    input_root_digest: Some((&req.input_files).into()),
    ..remexec::Action::default()
  };

  if let Some(timeout) = req.timeout {
    action.timeout = Some(prost_types::Duration::from(timeout));
  }

  let execute_request = remexec::ExecuteRequest {
    action_digest: Some((&digest(&action)?).into()),
    instance_name: instance_name.unwrap_or_else(|| "".to_owned()),
    ..remexec::ExecuteRequest::default()
  };

  Ok((action, command, execute_request))
}

pub async fn populate_fallible_execution_result_for_timeout(
  store: &Store,
  description: &str,
  timeout: Option<Duration>,
  elapsed: Duration,
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
    platform,
    metadata: ProcessResultMetadata::default(),
  })
}

/// Convert an ActionResult into a FallibleProcessResultWithPlatform.
///
/// HACK: The caching CommandRunner stores the digest of the Directory that merges all output
/// files and output directories in the `tree_digest` field of the `output_directories` field
/// of the ActionResult/ExecuteResponse stored in the local cache. When
/// `treat_tree_digest_as_final_directory_hack` is true, then that final merged directory
/// will be extracted from the tree_digest of the single output directory.
pub fn populate_fallible_execution_result(
  store: Store,
  action_result: &remexec::ActionResult,
  platform: Platform,
  treat_tree_digest_as_final_directory_hack: bool,
) -> BoxFuture<Result<FallibleProcessResultWithPlatform, String>> {
  future::try_join3(
    extract_stdout(&store, action_result),
    extract_stderr(&store, action_result),
    extract_output_files(
      store,
      action_result,
      treat_tree_digest_as_final_directory_hack,
    ),
  )
  .and_then(
    move |(stdout_digest, stderr_digest, output_directory)| async move {
      Ok(FallibleProcessResultWithPlatform {
        stdout_digest,
        stderr_digest,
        exit_code: action_result.exit_code,
        output_directory,
        platform,
        metadata: action_result
          .execution_metadata
          .clone()
          .map_or(ProcessResultMetadata::default(), |metadata| metadata.into()),
      })
    },
  )
  .boxed()
}

fn extract_stdout<'a>(
  store: &Store,
  action_result: &'a remexec::ActionResult,
) -> BoxFuture<'a, Result<Digest, String>> {
  let store = store.clone();
  async move {
    if let Some(digest_proto) = &action_result.stdout_digest {
      let stdout_digest_result: Result<Digest, String> = digest_proto.try_into();
      let stdout_digest =
        stdout_digest_result.map_err(|err| format!("Error extracting stdout: {}", err))?;
      Ok(stdout_digest)
    } else {
      let stdout_raw = Bytes::copy_from_slice(&action_result.stdout_raw);
      let digest = store
        .store_file_bytes(stdout_raw, true)
        .map_err(move |error| format!("Error storing raw stdout: {:?}", error))
        .await?;
      Ok(digest)
    }
  }
  .boxed()
}

fn extract_stderr<'a>(
  store: &Store,
  action_result: &'a remexec::ActionResult,
) -> BoxFuture<'a, Result<Digest, String>> {
  let store = store.clone();
  async move {
    if let Some(digest_proto) = &action_result.stderr_digest {
      let stderr_digest_result: Result<Digest, String> = digest_proto.try_into();
      let stderr_digest =
        stderr_digest_result.map_err(|err| format!("Error extracting stderr: {}", err))?;
      Ok(stderr_digest)
    } else {
      let stderr_raw = Bytes::copy_from_slice(&action_result.stderr_raw);
      let digest = store
        .store_file_bytes(stderr_raw, true)
        .map_err(move |error| format!("Error storing raw stderr: {:?}", error))
        .await?;
      Ok(digest)
    }
  }
  .boxed()
}

pub fn extract_output_files(
  store: Store,
  action_result: &remexec::ActionResult,
  treat_tree_digest_as_final_directory_hack: bool,
) -> BoxFuture<'static, Result<Digest, String>> {
  // HACK: The caching CommandRunner stores the digest of the Directory that merges all output
  // files and output directories in the `tree_digest` field of the `output_directories` field
  // of the ActionResult/ExecuteResponse stored in the local cache. When
  // `treat_tree_digest_as_final_directory_hack` is true, then this code will extract that
  // directory from the tree_digest and skip the merging performed by the remainder of this
  // method.
  if treat_tree_digest_as_final_directory_hack {
    match &action_result.output_directories[..] {
      &[ref directory] => {
        match require_digest(directory.tree_digest.as_ref()) {
          Ok(digest) => return future::ready::<Result<Digest, String>>(Ok(digest)).boxed(),
          Err(err) => return futures::future::err(err).boxed(),
        };
      }
      _ => {
        return futures::future::err(
          "illegal state: treat_tree_digest_as_final_directory_hack expected single output directory".to_owned()
        ).boxed();
      }
    }
  }

  // Get Digests of output Directories.
  // Then we'll make a Directory for the output files, and merge them.
  let mut directory_digests = Vec::with_capacity(action_result.output_directories.len() + 1);
  // TODO: Maybe take rather than clone
  let output_directories = action_result.output_directories.clone();
  for dir in output_directories {
    let store = store.clone();
    directory_digests.push(
      (async move {
        // The `OutputDirectory` contains the digest of a `Tree` proto which contains
        // the `Directory` proto of the root directory of this `OutputDirectory` plus all
        // of the `Directory` protos for child directories of that root.

        // Retrieve the Tree proto and hash its root `Directory` proto to obtain the digest
        // of the output directory needed to construct the series of `Directory` protos needed
        // for the final merge of the output directories.
        let tree_digest: Digest = require_digest(dir.tree_digest.as_ref())?;
        let root_digest_opt = store.load_tree_from_remote(tree_digest).await?;
        let root_digest = root_digest_opt
          .ok_or_else(|| format!("Tree with digest {:?} was not in remote", tree_digest))?;

        let mut digest = root_digest;

        if !dir.path.is_empty() {
          for component in dir.path.rsplit('/') {
            let component = component.to_owned();
            let directory = remexec::Directory {
              directories: vec![remexec::DirectoryNode {
                name: component,
                digest: Some((&digest).into()),
              }],
              ..remexec::Directory::default()
            };
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
    .output_files
    .iter()
    .map(|output_file| {
      let output_file_path_buf = PathBuf::from(output_file.path.clone());
      let digest: Result<Digest, String> = require_digest(output_file.digest.as_ref());
      path_map.insert(output_file_path_buf.clone(), digest?);
      Ok(PathStat::file(
        output_file_path_buf.clone(),
        File {
          path: output_file_path_buf,
          is_executable: output_file.is_executable,
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
    fn store_by_digest(&self, file: File) -> future::BoxFuture<'static, Result<Digest, String>> {
      match self.map_of_paths_to_digests.get(&file.path) {
        Some(digest) => future::ok(*digest),
        None => future::err(format!(
          "Didn't know digest for path in remote execution response: {:?}",
          file.path
        )),
      }
      .boxed()
    }
  }

  async move {
    let files_digest = Snapshot::digest_from_path_stats(
      store.clone(),
      StoreOneOffRemoteDigest::new(path_map),
      path_stats,
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
  }
  .boxed()
}

/// Apply REAPI request metadata header to a `tonic::Request`.
fn apply_headers<T>(mut request: Request<T>, build_id: &str) -> Request<T> {
  let reapi_request_metadata = remexec::RequestMetadata {
    tool_details: Some(remexec::ToolDetails {
      tool_name: "pants".into(),
      ..remexec::ToolDetails::default()
    }),
    tool_invocation_id: build_id.to_string(),
    ..remexec::RequestMetadata::default()
  };

  let md = request.metadata_mut();
  md.insert_bin(
    "google.devtools.remoteexecution.v1test.requestmetadata-bin",
    BinaryMetadataValue::try_from_bytes(&reapi_request_metadata.to_bytes()).unwrap(),
  );

  request
}

/// Check the remote Action Cache for a cached result of running the given `action_digest`.
///
/// This check is necessary because some RE servers do not short-circuit the Execute method
/// by checking the Action Cache (e.g., BuildBarn). Thus, this client must check the cache
/// explicitly in order to avoid duplicating already-cached work. This behavior matches
/// the Bazel RE client.
pub async fn check_action_cache(
  action_digest: Digest,
  metadata: &ProcessMetadata,
  platform: Platform,
  context: &Context,
  action_cache_client: Arc<ActionCacheClient<Channel>>,
  store: Store,
  eager_fetch: bool,
) -> Result<Option<FallibleProcessResultWithPlatform>, String> {
  context
    .workunit_store
    .increment_counter(Metric::RemoteCacheRequests, 1);

  let request = remexec::GetActionResultRequest {
    action_digest: Some(action_digest.into()),
    instance_name: metadata
      .instance_name
      .as_ref()
      .cloned()
      .unwrap_or_else(String::new),
    ..remexec::GetActionResultRequest::default()
  };

  let mut client = action_cache_client.as_ref().clone();
  let request = apply_headers(Request::new(request), &context.build_id);
  let action_result_response = client.get_action_result(request).await;

  match action_result_response {
    Ok(action_result) => {
      let action_result = action_result.into_inner();
      let response =
        populate_fallible_execution_result(store.clone(), &action_result, platform, false).await?;
      if eager_fetch {
        future::try_join_all(vec![
          store.ensure_local_has_file(response.stdout_digest).boxed(),
          store.ensure_local_has_file(response.stderr_digest).boxed(),
          store
            .ensure_local_has_recursive_directory(response.output_directory)
            .boxed(),
        ])
        .await?;
      };
      context
        .workunit_store
        .increment_counter(Metric::RemoteCacheRequestsCached, 1);
      Ok(Some(response))
    }
    Err(status) => match status.code() {
      Code::NotFound => {
        context
          .workunit_store
          .increment_counter(Metric::RemoteCacheRequestsUncached, 1);
        Ok(None)
      }
      _ => {
        context
          .workunit_store
          .increment_counter(Metric::RemoteCacheReadErrors, 1);
        Err(status_to_str(status))
      }
    },
  }
}

pub async fn store_proto_locally<P: prost::Message>(
  store: &Store,
  proto: &P,
) -> Result<Digest, String> {
  store
    .store_file_bytes(proto.to_bytes(), true)
    .await
    .map_err(|e| format!("Error saving proto to local store: {:?}", e))
}

pub async fn ensure_action_stored_locally(
  store: &Store,
  command: &Command,
  action: &Action,
) -> Result<(Digest, Digest), String> {
  let (command_digest, action_digest) = future::try_join(
    store_proto_locally(store, command),
    store_proto_locally(store, action),
  )
  .await?;

  Ok((command_digest, action_digest))
}

pub async fn ensure_action_uploaded(
  store: &Store,
  command_digest: Digest,
  action_digest: Digest,
  input_files: Digest,
) -> Result<(), String> {
  let _ = store
    .ensure_remote_has_recursive(vec![command_digest, action_digest, input_files])
    .await?;
  Ok(())
}

pub fn format_error(error: &StatusProto) -> String {
  let error_code_enum = Code::from_i32(error.code);
  let error_code = match error_code_enum {
    Code::Unknown => format!("{:?}", error.code),
    x => format!("{:?}", x),
  };
  format!("{}: {}", error_code, error.message)
}

pub fn digest<T: prost::Message>(message: &T) -> Result<Digest, String> {
  Ok(Digest::of_bytes(&message.to_bytes()))
}
