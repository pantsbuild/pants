// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::BTreeMap;
use std::convert::TryInto;
use std::fmt::{self, Debug};
use std::io::Cursor;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bytes::Bytes;
use futures::future;
use futures::{Stream, StreamExt};
use log::{debug, trace, warn, Level};
use prost::Message;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::gen::google::longrunning::{
  operations_client::OperationsClient, CancelOperationRequest, Operation,
};
use protos::gen::google::rpc::{PreconditionFailure, Status as StatusProto};
use rand::{thread_rng, Rng};
use remexec::{
  capabilities_client::CapabilitiesClient, execution_client::ExecutionClient,
  execution_stage::Value as ExecutionStageValue, Action, Command, ExecuteRequest, ExecuteResponse,
  ExecutedActionMetadata, ServerCapabilities, WaitExecutionRequest,
};
use tonic::metadata::BinaryMetadataValue;
use tonic::{Code, Request, Status};

use concrete_time::TimeSpan;
use fs::{self, DirectoryDigest, EMPTY_DIRECTORY_DIGEST};
use grpc_util::headers_to_http_header_map;
use grpc_util::prost::MessageExt;
use grpc_util::{layered_service, status_to_str, LayeredService};
use hashing::{Digest, Fingerprint};
use store::{Store, StoreError};
use task_executor::Executor;
use workunit_store::{
  in_workunit, Metric, ObservationMetric, RunId, RunningWorkunit, SpanId, UserMetadataItem,
  WorkunitMetadata, WorkunitStore,
};

use process_execution::{
  make_execute_request, populate_fallible_execution_result, Context, EntireExecuteRequest,
  FallibleProcessResultWithPlatform, Process, ProcessError, ProcessExecutionEnvironment,
  ProcessResultMetadata, ProcessResultSource,
};

#[derive(Debug)]
pub enum OperationOrStatus {
  Operation(Operation),
  Status(StatusProto),
}

#[derive(Debug, PartialEq, Eq)]
pub enum ExecutionError {
  Fatal(ProcessError),
  // Digests are Files and Directories which have been reported to be missing remotely (unlike
  // `{Process,Store}Error::MissingDigest`, which indicates that a digest doesn't exist anywhere
  // in the configured Stores). May be incomplete.
  MissingRemoteDigests(Vec<Digest>),
  // The server indicated that the request hit a timeout. Generally this is the timeout that the
  // client has pushed down on the ExecutionRequest.
  Timeout,
  // String is the error message.
  Retryable(String),
}

/// Implementation of CommandRunner that runs a command via the Bazel Remote Execution API
/// (<https://docs.google.com/document/d/1AaGk7fOPByEvpAbqeXIyE8HX_A3_axxNnvroblTZ_6s/edit>).
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
  instance_name: Option<String>,
  process_cache_namespace: Option<String>,
  append_only_caches_base_path: Option<String>,
  store: Store,
  executor: Executor,
  execution_client: Arc<ExecutionClient<LayeredService>>,
  operations_client: Arc<OperationsClient<LayeredService>>,
  overall_deadline: Duration,
  retry_interval_duration: Duration,
  capabilities_cell: Arc<OnceCell<ServerCapabilities>>,
  capabilities_client: Arc<CapabilitiesClient<LayeredService>>,
}

enum StreamOutcome {
  Complete(OperationOrStatus),
  StreamClosed,
}

enum OperationStreamItem {
  Running(ExecutionStageValue),
  Outcome(StreamOutcome),
}

/// A single remote Operation, with a `Drop` implementation to cancel the work if our client goes
/// away.
struct RunningOperation {
  name: Option<String>,
  operations_client: Arc<OperationsClient<LayeredService>>,
  executor: Executor,
  process_level: Level,
  process_description: String,
}

impl RunningOperation {
  fn new(
    operations_client: Arc<OperationsClient<LayeredService>>,
    executor: Executor,
    process_level: Level,
    process_description: String,
  ) -> Self {
    Self {
      name: None,
      operations_client,
      executor,
      process_level,
      process_description,
    }
  }

  /// Marks the operation completed, which will avoid attempts to cancel it when this struct is
  /// dropped.
  fn completed(&mut self) {
    let _ = self.name.take();
  }
}

impl Drop for RunningOperation {
  fn drop(&mut self) {
    if let Some(operation_name) = self.name.take() {
      debug!("Canceling remote operation {operation_name}");
      let mut operations_client = self.operations_client.as_ref().clone();
      let fut = self.executor.native_spawn(async move {
        operations_client
          .cancel_operation(CancelOperationRequest {
            name: operation_name,
          })
          .await
      });
      drop(fut);
    }
  }
}

impl CommandRunner {
  /// Construct a new CommandRunner
  pub async fn new(
    execution_address: &str,
    instance_name: Option<String>,
    process_cache_namespace: Option<String>,
    append_only_caches_base_path: Option<String>,
    root_ca_certs: Option<Vec<u8>>,
    headers: BTreeMap<String, String>,
    store: Store,
    executor: Executor,
    overall_deadline: Duration,
    retry_interval_duration: Duration,
    execution_concurrency_limit: usize,
    capabilities_cell_opt: Option<Arc<OnceCell<ServerCapabilities>>>,
  ) -> Result<Self, String> {
    let execution_use_tls = execution_address.starts_with("https://");

    let tls_client_config = if execution_use_tls {
      Some(grpc_util::tls::Config::new_without_mtls(root_ca_certs).try_into()?)
    } else {
      None
    };

    let execution_endpoint = grpc_util::create_channel(
      execution_address,
      tls_client_config.as_ref().filter(|_| execution_use_tls),
    )
    .await?;
    let execution_http_headers = headers_to_http_header_map(&headers)?;
    let execution_channel = layered_service(
      execution_endpoint,
      execution_concurrency_limit,
      execution_http_headers,
      None,
    );
    let execution_client = Arc::new(ExecutionClient::new(execution_channel.clone()));
    let operations_client = Arc::new(OperationsClient::new(execution_channel.clone()));
    let capabilities_client = Arc::new(CapabilitiesClient::new(execution_channel));

    let command_runner = CommandRunner {
      instance_name,
      process_cache_namespace,
      append_only_caches_base_path,
      execution_client,
      operations_client,
      store,
      executor,
      overall_deadline,
      retry_interval_duration,
      capabilities_cell: capabilities_cell_opt.unwrap_or_else(|| Arc::new(OnceCell::new())),
      capabilities_client,
    };

    Ok(command_runner)
  }

  async fn get_capabilities(&self) -> Result<&remexec::ServerCapabilities, String> {
    let capabilities_fut = async {
      let mut request = remexec::GetCapabilitiesRequest::default();
      if let Some(s) = self.instance_name.as_ref() {
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

  async fn wait_on_operation_stream_item<S>(
    stream: &mut S,
    context: &Context,
    running_operation: &mut RunningOperation,
    start_time_opt: &mut Option<Instant>,
  ) -> OperationStreamItem
  where
    S: Stream<Item = Result<Operation, Status>> + Unpin,
  {
    let item = stream.next().await;

    if let Some(start_time) = start_time_opt.take() {
      let timing: Result<u64, _> = Instant::now()
        .duration_since(start_time)
        .as_micros()
        .try_into();
      if let Ok(obs) = timing {
        context.workunit_store.record_observation(
          ObservationMetric::RemoteExecutionRPCFirstResponseTimeMicros,
          obs,
        );
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
        running_operation.name = Some(operation.name.clone()).filter(|s| !s.trim().is_empty());

        if operation.done {
          // Continue monitoring if the operation is not complete.
          OperationStreamItem::Outcome(StreamOutcome::Complete(OperationOrStatus::Operation(
            operation,
          )))
        } else {
          // Otherwise, return to the main loop with the operation as the result.
          OperationStreamItem::Running(
            Self::maybe_extract_execution_stage(&operation).unwrap_or(ExecutionStageValue::Unknown),
          )
        }
      }

      Some(Err(err)) => {
        debug!("wait_on_operation_stream: got error: {:?}", err);
        let status_proto = StatusProto {
          code: err.code() as i32,
          message: err.message().to_string(),
          ..StatusProto::default()
        };
        OperationStreamItem::Outcome(StreamOutcome::Complete(OperationOrStatus::Status(
          status_proto,
        )))
      }

      None => {
        // Stream disconnected unexpectedly.
        debug!("wait_on_operation_stream: unexpected disconnect from RE server");
        OperationStreamItem::Outcome(StreamOutcome::StreamClosed)
      }
    }
  }

  /// Monitors the operation stream returned by the REv2 Execute and WaitExecution methods.
  /// Outputs progress reported by the server and returns the next actionable operation
  /// or gRPC status back to the main loop (plus the operation name so the main loop can
  /// reconnect).
  async fn wait_on_operation_stream<S>(
    mut stream: S,
    context: &Context,
    running_operation: &mut RunningOperation,
  ) -> StreamOutcome
  where
    S: Stream<Item = Result<Operation, Status>> + Unpin + Send,
  {
    let mut start_time_opt = Some(Instant::now());

    trace!(
      "wait_on_operation_stream (build_id={}): monitoring stream",
      &context.build_id
    );

    // If the server returns an `ExecutionStage` other than `Unknown`, then we assume that it
    // implements reporting when the operation actually begins `Executing` (as opposed to being
    // `Queued`, etc), and will wait to create a workunit until we see the `Executing` stage.
    //
    // We start by consuming the prefix of the stream before we receive an `Executing` or `Unknown` stage.
    loop {
      match Self::wait_on_operation_stream_item(
        &mut stream,
        context,
        running_operation,
        &mut start_time_opt,
      )
      .await
      {
        OperationStreamItem::Running(
          ExecutionStageValue::Unknown | ExecutionStageValue::Executing,
        ) => {
          // Either the server doesn't know how to report the stage, or the operation has
          // actually begun executing serverside: proceed to the suffix.
          break;
        }
        OperationStreamItem::Running(_) => {
          // The operation has not reached an ExecutionStage that we recognize as
          // "executing" (likely: it is queued, doing a cache lookup, etc): keep waiting.
          continue;
        }
        OperationStreamItem::Outcome(outcome) => return outcome,
      }
    }

    // Start a workunit to represent the execution of the work, and consume the rest of the stream.
    in_workunit!(
      "run_remote_process",
      // NB: See engine::nodes::NodeKey::workunit_level for more information on why this workunit
      // renders at the Process's level.
      running_operation.process_level,
      desc = Some(running_operation.process_description.clone()),
      |_workunit| async move {
        loop {
          match Self::wait_on_operation_stream_item(
            &mut stream,
            context,
            running_operation,
            &mut start_time_opt,
          )
          .await
          {
            OperationStreamItem::Running(
              ExecutionStageValue::Queued | ExecutionStageValue::CacheCheck,
            ) => {
              // The server must have cancelled and requeued the work: although this isn't an error
              // per-se, it is much easier for us to re-open the stream than to treat this as a
              // nested loop. In particular:
              // 1. we can't break/continue out of a workunit
              // 2. the stream needs to move into the workunit, and can't move back out
              break StreamOutcome::StreamClosed;
            }
            OperationStreamItem::Running(_) => {
              // The operation is still running.
              continue;
            }
            OperationStreamItem::Outcome(outcome) => break outcome,
          }
        }
      }
    )
    .await
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
          Level::Trace,
          time_span,
          parent_id,
          &workunit_store,
          WorkunitMetadata::default(),
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
          Level::Trace,
          time_span,
          parent_id,
          &workunit_store,
          WorkunitMetadata::default(),
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
          Level::Trace,
          time_span,
          parent_id,
          &workunit_store,
          WorkunitMetadata::default(),
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
          Level::Trace,
          time_span,
          parent_id,
          &workunit_store,
          WorkunitMetadata::default(),
        ),
        Err(s) => warn!("{}", s),
      }
    }
  }

  fn extract_missing_digests(&self, precondition_failure: &PreconditionFailure) -> ExecutionError {
    let mut missing_digests = Vec::with_capacity(precondition_failure.violations.len());

    for violation in &precondition_failure.violations {
      if violation.r#type != "MISSING" {
        return ExecutionError::Fatal(
          format!("Unknown PreconditionFailure violation: {violation:?}").into(),
        );
      }

      let parts: Vec<_> = violation.subject.split('/').collect();
      if parts.len() != 3 || parts[0] != "blobs" {
        return ExecutionError::Fatal(
          format!(
            "Received FailedPrecondition MISSING but didn't recognize subject {}",
            violation.subject
          )
          .into(),
        );
      }

      let fingerprint = match Fingerprint::from_hex_string(parts[1]) {
        Ok(f) => f,
        Err(e) => {
          return ExecutionError::Fatal(
            format!("Bad digest in missing blob: {}: {}", parts[1], e).into(),
          )
        }
      };

      let size = match parts[2].parse::<usize>() {
        Ok(s) => s,
        Err(e) => {
          return ExecutionError::Fatal(
            format!("Missing blob had bad size: {}: {}", parts[2], e).into(),
          )
        }
      };

      missing_digests.push(Digest::new(fingerprint, size));
    }

    if missing_digests.is_empty() {
      return ExecutionError::Fatal(
        "Error from remote execution: FailedPrecondition, but no details"
          .to_owned()
          .into(),
      );
    }

    ExecutionError::MissingRemoteDigests(missing_digests)
  }

  /// If set, extract `ExecuteOperationMetadata` from the `Operation`.
  fn maybe_extract_execution_stage(operation: &Operation) -> Option<ExecutionStageValue> {
    let metadata = operation.metadata.as_ref()?;

    let eom = remexec::ExecuteOperationMetadata::decode(&metadata.value[..])
      .map(Some)
      .unwrap_or_else(|e| {
        log::warn!("Invalid ExecuteOperationMetadata from server: {e:?}");
        None
      })?;

    ExecutionStageValue::from_i32(eom.stage)
  }

  // pub(crate) for testing
  pub(crate) async fn extract_execute_response(
    &self,
    run_id: RunId,
    environment: ProcessExecutionEnvironment,
    operation_or_status: OperationOrStatus,
  ) -> Result<FallibleProcessResultWithPlatform, ExecutionError> {
    trace!("Got operation response: {:?}", operation_or_status);

    let status = match operation_or_status {
      OperationOrStatus::Operation(operation) => {
        assert!(operation.done, "operation was not marked done");

        use protos::gen::google::longrunning::operation::Result as OperationResult;
        let execute_response = match operation.result {
          Some(OperationResult::Response(response_any)) => {
            remexec::ExecuteResponse::decode(&response_any.value[..]).map_err(|e| {
              ExecutionError::Fatal(format!("Invalid ExecuteResponse: {e:?}").into())
            })?
          }
          Some(OperationResult::Error(rpc_status)) => {
            // Infrastructure error. Retry it.
            let msg = format_error(&rpc_status);
            debug!("got operation error for runid {:?}: {}", &run_id, &msg);
            return Err(ExecutionError::Retryable(msg));
          }
          None => {
            return Err(ExecutionError::Fatal(
              "Operation finished but no response supplied"
                .to_owned()
                .into(),
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
              "REv2 protocol violation: action result not set"
                .to_owned()
                .into(),
            ));
          };

          return populate_fallible_execution_result(
            self.store.clone(),
            run_id,
            action_result,
            false,
            if execute_response.cached_result {
              ProcessResultSource::HitRemotely
            } else {
              ProcessResultSource::Ran
            },
            environment,
          )
          .await
          .map_err(|e| ExecutionError::Fatal(e.into()));
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
          return Err(ExecutionError::Fatal(status.message.into()));
        } else if status.details.len() > 1 {
          // TODO(tonic): Should we be able to handle multiple details protos?
          return Err(ExecutionError::Fatal(
            "too many detail protos for precondition failure"
              .to_owned()
              .into(),
          ));
        } else {
          &status.details[0]
        };

        let full_name = format!("type.googleapis.com/{}", "google.rpc.PreconditionFailure");
        if details.type_url != full_name {
          return Err(ExecutionError::Fatal(
            format!(
            "Received PreconditionFailure, but didn't know how to resolve it: {}, protobuf type {}",
            status.message, details.type_url
          )
            .into(),
          ));
        }

        // Decode the precondition failure.
        let precondition_failure = PreconditionFailure::decode(Cursor::new(&details.value))
          .map_err(|e| {
            ExecutionError::Fatal(
              format!("Error deserializing PreconditionFailure proto: {e:?}").into(),
            )
          })?;

        Err(self.extract_missing_digests(&precondition_failure))
      }

      Code::Aborted
      | Code::Internal
      | Code::ResourceExhausted
      | Code::Unavailable
      | Code::Unknown => Err(ExecutionError::Retryable(status.message)),
      code => Err(ExecutionError::Fatal(
        format!(
          "Error from remote execution: {:?}: {:?}",
          code, status.message,
        )
        .into(),
      )),
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
    workunit: &mut RunningWorkunit,
  ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
    const MAX_RETRIES: u32 = 5;
    const MAX_BACKOFF_DURATION: Duration = Duration::from_secs(10);

    let start_time = Instant::now();

    let mut running_operation = RunningOperation::new(
      self.operations_client.clone(),
      self.executor.clone(),
      process.level,
      process.description.clone(),
    );
    let mut num_retries = 0;

    loop {
      // If we are currently retrying a request, then delay using an exponential backoff.
      if num_retries > 0 {
        workunit.increment_counter(Metric::RemoteExecutionRPCRetries, 1);

        let multiplier = thread_rng().gen_range(0..2_u32.pow(num_retries) + 1);
        let sleep_time = self.retry_interval_duration * multiplier;
        let sleep_time = sleep_time.min(MAX_BACKOFF_DURATION);
        debug!("delaying {:?} before retry", sleep_time);
        tokio::time::sleep(sleep_time).await;
      }

      let rpc_result = match running_operation.name {
        None => {
          // The request has not been submitted yet. Submit the request using the REv2
          // Execute method.
          debug!(
            "no current operation: submitting execute request: build_id={}; execute_request={:?}",
            context.build_id, &execute_request
          );
          workunit.increment_counter(Metric::RemoteExecutionRPCExecute, 1);
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
          workunit.increment_counter(Metric::RemoteExecutionRPCWaitExecution, 1);
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
          let stream_outcome =
            Self::wait_on_operation_stream(operation_stream, context, &mut running_operation).await;

          match stream_outcome {
            StreamOutcome::Complete(status) => {
              trace!(
                "wait_on_operation_stream (build_id={}) returned completion={:?}",
                context.build_id,
                status
              );
              // We completed this operation.
              running_operation.completed();
              status
            }
            StreamOutcome::StreamClosed => {
              trace!(
                "wait_on_operation_stream (build_id={}) returned stream close, \
                     will retry operation_name={:?}",
                context.build_id,
                running_operation.name
              );

              // Check if the number of request attempts sent thus far have exceeded the number
              // of retries allowed since the last successful connection. (There is no point in
              // continually submitting a request if ultimately futile.)
              if num_retries >= MAX_RETRIES {
                workunit.increment_counter(Metric::RemoteExecutionRPCErrors, 1);
                return Err(
                  "Too many failures from server. The last event was the server disconnecting with no error given.".to_owned().into(),
                );
              } else {
                // Increment the retry counter and allow loop to retry.
                num_retries += 1;
              }

              // Iterate the loop to reconnect to the operation.
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
          // `OperationOrStatus` always represents a completed operation, so this operation
          // is completed.
          running_operation.completed();
          OperationOrStatus::Status(status_proto)
        }
      };

      match self
        .extract_execute_response(
          context.run_id,
          process.execution_environment.clone(),
          actionable_result,
        )
        .await
      {
        Ok(result) => return Ok(result),
        Err(err) => match err {
          ExecutionError::Fatal(e) => {
            workunit.increment_counter(Metric::RemoteExecutionRPCErrors, 1);
            return Err(e);
          }
          ExecutionError::Retryable(e) => {
            // Check if the number of request attempts sent thus far have exceeded the number
            // of retries allowed since the last successful connection. (There is no point in
            // continually submitting a request if ultimately futile.)
            trace!("retryable error: {}", e);
            if num_retries >= MAX_RETRIES {
              workunit.increment_counter(Metric::RemoteExecutionRPCErrors, 1);
              return Err(format!("Too many failures from server. The last error was: {e}").into());
            } else {
              // Increment the retry counter and allow loop to retry.
              num_retries += 1;
            }
          }
          ExecutionError::MissingRemoteDigests(missing_digests) => {
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
            workunit.increment_counter(Metric::RemoteExecutionTimeouts, 1);
            let result = populate_fallible_execution_result_for_timeout(
              &self.store,
              context,
              &process.description,
              process.timeout,
              start_time.elapsed(),
              process.execution_environment,
            )
            .await?;
            return Ok(result);
          }
        },
      }
    }
  }
}

impl Debug for CommandRunner {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    f.debug_struct("remote::CommandRunner")
      .finish_non_exhaustive()
  }
}

#[async_trait]
impl process_execution::CommandRunner for CommandRunner {
  /// Run the given Process via the Remote Execution API.
  async fn run(
    &self,
    context: Context,
    _workunit: &mut RunningWorkunit,
    request: Process,
  ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
    // Retrieve capabilities for this server.
    let capabilities = self.get_capabilities().await?;
    trace!("RE capabilities: {:?}", &capabilities);

    // Construct the REv2 ExecuteRequest and related data for this execution request.
    let EntireExecuteRequest {
      action,
      command,
      execute_request,
      input_root_digest,
    } = make_execute_request(
      &request,
      self.instance_name.clone(),
      self.process_cache_namespace.clone(),
      &self.store,
      self
        .append_only_caches_base_path
        .as_ref()
        .map(|s| s.as_ref()),
    )
    .await?;
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
    let (command_digest, action_digest) =
      ensure_action_stored_locally(&self.store, &command, &action).await?;

    // Upload the action (and related data, i.e. the embedded command and input files).
    ensure_action_uploaded(
      &self.store,
      command_digest,
      action_digest,
      Some(input_root_digest),
    )
    .await?;

    // Submit the execution request to the RE server for execution.
    let context2 = context.clone();
    in_workunit!(
      "run_execute_request",
      // NB: The process has not actually started running until the server has notified us that it
      // has: see `wait_on_operation_stream`.
      Level::Debug,
      user_metadata = vec![(
        "action_digest".to_owned(),
        UserMetadataItem::String(format!("{action_digest:?}")),
      )],
      |workunit| async move {
        workunit.increment_counter(Metric::RemoteExecutionRequests, 1);
        let result_fut = self.run_execute_request(execute_request, request, &context2, workunit);

        // Detect whether the operation ran or hit the deadline timeout.
        match tokio::time::timeout(deadline_duration, result_fut).await {
          Ok(Ok(result)) => {
            workunit.increment_counter(Metric::RemoteExecutionSuccess, 1);
            Ok(result)
          }
          Ok(Err(err)) => {
            workunit.increment_counter(Metric::RemoteExecutionErrors, 1);
            Err(err.enrich(&format!("For action {action_digest:?}")))
          }
          Err(tokio::time::error::Elapsed { .. }) => {
            // The Err in this match arm originates from the timeout future.
            debug!(
              "remote execution for build_id={} timed out after {:?}",
              &build_id, deadline_duration
            );
            workunit.update_metadata(|initial| {
              let initial = initial.map(|(m, _)| m).unwrap_or_default();
              Some((
                WorkunitMetadata {
                  desc: Some(format!(
                    "remote execution timed out after {deadline_duration:?}"
                  )),
                  ..initial
                },
                Level::Error,
              ))
            });
            workunit.increment_counter(Metric::RemoteExecutionTimeouts, 1);
            Err(format!("remote execution timed out after {deadline_duration:?}").into())
          }
        }
      },
    )
    .await
  }

  async fn shutdown(&self) -> Result<(), String> {
    Ok(())
  }
}

fn maybe_add_workunit(
  result_cached: bool,
  name: &'static str,
  level: Level,
  time_span: concrete_time::TimeSpan,
  parent_id: Option<SpanId>,
  workunit_store: &WorkunitStore,
  metadata: WorkunitMetadata,
) {
  if !result_cached && workunit_store.max_level() >= level {
    let start_time: SystemTime = SystemTime::UNIX_EPOCH + time_span.start.into();
    let end_time: SystemTime = start_time + time_span.duration.into();
    workunit_store.add_completed_workunit(name, level, start_time, end_time, parent_id, metadata);
  }
}

async fn populate_fallible_execution_result_for_timeout(
  store: &Store,
  context: &Context,
  description: &str,
  timeout: Option<Duration>,
  elapsed: Duration,
  environment: ProcessExecutionEnvironment,
) -> Result<FallibleProcessResultWithPlatform, String> {
  let timeout_msg = if let Some(timeout) = timeout {
    format!("user timeout of {timeout:?} after {elapsed:?}")
  } else {
    format!("server timeout after {elapsed:?}")
  };
  let stdout = Bytes::from(format!("Exceeded {timeout_msg} for {description}"));
  let stdout_digest = store.store_file_bytes(stdout, true).await?;

  Ok(FallibleProcessResultWithPlatform {
    stdout_digest,
    stderr_digest: hashing::EMPTY_DIGEST,
    exit_code: -libc::SIGTERM,
    output_directory: EMPTY_DIRECTORY_DIGEST.clone(),
    metadata: ProcessResultMetadata::new(
      Some(elapsed.into()),
      ProcessResultSource::Ran,
      environment,
      context.run_id,
    ),
  })
}

/// Apply REAPI request metadata header to a `tonic::Request`.
pub(crate) fn apply_headers<T>(mut request: Request<T>, build_id: &str) -> Request<T> {
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
    BinaryMetadataValue::try_from(reapi_request_metadata.to_bytes()).unwrap(),
  );

  request
}

pub async fn store_proto_locally<P: prost::Message>(
  store: &Store,
  proto: &P,
) -> Result<Digest, String> {
  store
    .store_file_bytes(proto.to_bytes(), true)
    .await
    .map_err(|e| format!("Error saving proto to local store: {e:?}"))
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

///
/// Ensure that the Action and Command (and optionally their input files, likely depending on
/// whether we are in a remote execution context, or a pure cache-usage context) are uploaded.
///
pub async fn ensure_action_uploaded(
  store: &Store,
  command_digest: Digest,
  action_digest: Digest,
  input_files: Option<DirectoryDigest>,
) -> Result<(), StoreError> {
  in_workunit!(
    "ensure_action_uploaded",
    Level::Trace,
    desc = Some(format!("ensure action uploaded for {action_digest:?}")),
    |_workunit| async move {
      let mut digests = vec![command_digest, action_digest];
      if let Some(input_files) = input_files {
        // TODO: Port ensure_remote_has_recursive. See #13112.
        store
          .ensure_directory_digest_persisted(input_files.clone())
          .await?;
        digests.push(input_files.todo_as_digest());
      }
      let _ = store.ensure_remote_has_recursive(digests).await?;
      Ok(())
    },
  )
  .await
}

pub fn format_error(error: &StatusProto) -> String {
  let error_code_enum = Code::from_i32(error.code);
  let error_code = match error_code_enum {
    Code::Unknown => format!("{:?}", error.code),
    x => format!("{x:?}"),
  };
  format!("{}: {}", error_code, error.message)
}
