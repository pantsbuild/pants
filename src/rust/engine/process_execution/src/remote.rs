use std::collections::HashMap;
use std::mem::drop;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bazel_protos;
use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use digest::{Digest as DigestTrait, FixedOutput};
use fs::{self, File, PathStat, Store};
use futures::{future, Future, Stream};
use futures_timer::Delay;
use grpcio;
use hashing::{Digest, Fingerprint};
use log::{debug, trace, warn};
use protobuf::{self, Message, ProtobufEnum};
use sha2::Sha256;
use time;

use super::{ExecuteProcessRequest, ExecutionStats, FallibleExecuteProcessResult};
use std;
use std::cmp::min;
use std::collections::btree_map::BTreeMap;

// Environment variable which is exclusively used for cache key invalidation.
// This may be not specified in an ExecuteProcessRequest, and may be populated only by the
// CommandRunner.
const CACHE_KEY_GEN_VERSION_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_GEN_VERSION";

#[derive(Debug)]
enum OperationOrStatus {
  Operation(bazel_protos::operations::Operation),
  Status(bazel_protos::status::Status),
}

#[derive(Clone)]
pub struct CommandRunner {
  cache_key_gen_version: Option<String>,
  instance_name: Option<String>,
  authorization_header: Option<String>,
  platform_properties: BTreeMap<String, String>,
  channel: grpcio::Channel,
  env: Arc<grpcio::Environment>,
  execution_client: Arc<bazel_protos::remote_execution_grpc::ExecutionClient>,
  operations_client: Arc<bazel_protos::operations_grpc::OperationsClient>,
  store: Store,
  futures_timer_thread: resettable::Resettable<futures_timer::HelperThread>,
}

#[derive(Debug, PartialEq)]
enum ExecutionError {
  // String is the error message.
  Fatal(String),
  // Digests are Files and Directories which have been reported to be missing. May be incomplete.
  MissingDigests(Vec<Digest>),
  // String is the operation name which can be used to poll the GetOperation gRPC API.
  NotFinished(String),
}

#[derive(Default)]
struct ExecutionHistory {
  attempts: Vec<ExecutionStats>,
  current_attempt: ExecutionStats,
}

impl CommandRunner {
  // The Execute API used to be unary, and became streaming. The contract of the streaming API is
  // that if the client closes the stream after one request, it should continue to function exactly
  // like the unary API.
  // For maximal compatibility with servers, we fall back to this unary-like behavior, and control
  // our own polling rates.
  // In the future, we may want to remove this behavior if servers reliably support the full stream
  // behavior.
  fn oneshot_execute(
    &self,
    execute_request: &Arc<bazel_protos::remote_execution::ExecuteRequest>,
  ) -> BoxFuture<OperationOrStatus, String> {
    let stream = try_future!(self
      .execution_client
      .execute_opt(&execute_request, self.call_option())
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
      .then(|maybe_operation_result| match maybe_operation_result {
        Ok(Some(operation)) => Ok(OperationOrStatus::Operation(operation)),
        Ok(None) => {
          Err("Didn't get proper stream response from server during remote execution".to_owned())
        }
        Err(err) => rpcerror_to_status_or_string(err).map(OperationOrStatus::Status),
      })
      .to_boxed()
  }
}

impl super::CommandRunner for CommandRunner {
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
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let operations_client = self.operations_client.clone();

    let store = self.store.clone();
    let execute_request_result = make_execute_request(
      &req,
      &self.instance_name,
      &self.cache_key_gen_version,
      self.platform_properties.clone(),
    );

    let ExecuteProcessRequest {
      description,
      timeout,
      input_files,
      ..
    } = req;

    let description2 = description.clone();

    match execute_request_result {
      Ok((action, command, execute_request)) => {
        let command_runner = self.clone();
        let command_runner2 = self.clone();
        let command_runner3 = self.clone();
        let execute_request = Arc::new(execute_request);
        let execute_request2 = execute_request.clone();
        let futures_timer_thread = self.futures_timer_thread.clone();

        let store2 = store.clone();
        let mut history = ExecutionHistory::default();

        self
          .store_proto_locally(&command)
          .join(self.store_proto_locally(&action))
          .and_then(move |(command_digest, action_digest)| {
            store2.ensure_remote_has_recursive(vec![command_digest, action_digest, input_files])
          })
          .and_then(move |summary| {
            history.current_attempt += summary;
            trace!(
              "Executing remotely request: {:?} (command: {:?})",
              execute_request,
              command
            );
            command_runner
              .oneshot_execute(&execute_request)
              .join(future::ok(history))
          })
          .and_then(move |(operation, history)| {
            let start_time = Instant::now();

            future::loop_fn(
              (history, operation, 0),
              move |(mut history, operation, iter_num)| {
                let description = description.clone();

                let execute_request2 = execute_request2.clone();
                let store = store.clone();
                let operations_client = operations_client.clone();
                let command_runner2 = command_runner2.clone();
                let command_runner3 = command_runner3.clone();
                let futures_timer_thread = futures_timer_thread.clone();
                let f = command_runner2.extract_execute_response(operation, &mut history);
                f.map(future::Loop::Break).or_else(move |value| {
                  match value {
                    ExecutionError::Fatal(err) => future::err(err).to_boxed(),
                    ExecutionError::MissingDigests(missing_digests) => {
                      let ExecutionHistory {
                        mut attempts,
                        current_attempt,
                      } = history;

                      trace!(
                        "Server reported missing digests ({:?}); trying to upload: {:?}",
                        current_attempt,
                        missing_digests,
                      );

                      attempts.push(current_attempt);
                      let history = ExecutionHistory {
                        attempts,
                        current_attempt: ExecutionStats::default(),
                      };

                      let execute_request = execute_request2.clone();
                      store
                        .ensure_remote_has_recursive(missing_digests)
                        .and_then(move |summary| {
                          let mut history = history;
                          history.current_attempt += summary;
                          command_runner2
                            .oneshot_execute(&execute_request)
                            .join(future::ok(history))
                        })
                        // Reset `iter_num` on `MissingDigests`
                        .map(|(operation, history)| future::Loop::Continue((history, operation, 0)))
                        .to_boxed()
                    }
                    ExecutionError::NotFinished(operation_name) => {
                      let mut operation_request =
                        bazel_protos::operations::GetOperationRequest::new();
                      operation_request.set_name(operation_name.clone());

                      let backoff_period = min(
                        CommandRunner::BACKOFF_MAX_WAIT_MILLIS,
                        (1 + iter_num) * CommandRunner::BACKOFF_INCR_WAIT_MILLIS,
                      );

                      // take the grpc result and cancel the op if too much time has passed.
                      let elapsed = start_time.elapsed();

                      if elapsed > timeout {
                        future::err(format!(
                          "Exceeded time out of {:?} with {:?} for operation {}, {}",
                          timeout, elapsed, operation_name, description
                        ))
                        .to_boxed()
                      } else {
                        // maybe the delay here should be the min of remaining time and the backoff period
                        Delay::new_handle(
                          Instant::now() + Duration::from_millis(backoff_period),
                          futures_timer_thread.with(futures_timer::HelperThread::handle),
                        )
                        .map_err(move |e| {
                          format!(
                            "Future-Delay errored at operation result polling for {}, {}: {}",
                            operation_name, description, e
                          )
                        })
                        .and_then(move |_| {
                          future::done(
                            operations_client
                              .get_operation_opt(&operation_request, command_runner3.call_option())
                              .or_else(move |err| {
                                rpcerror_recover_cancelled(operation_request.take_name(), err)
                              })
                              .map(OperationOrStatus::Operation)
                              .map_err(rpcerror_to_string),
                          )
                          .map(move |operation| {
                            future::Loop::Continue((history, operation, iter_num + 1))
                          })
                          .to_boxed()
                        })
                        .to_boxed()
                      }
                    }
                  }
                })
              },
            )
          })
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
  const BACKOFF_INCR_WAIT_MILLIS: u64 = 500;
  const BACKOFF_MAX_WAIT_MILLIS: u64 = 5000;

  pub fn new(
    address: &str,
    cache_key_gen_version: Option<String>,
    instance_name: Option<String>,
    root_ca_certs: Option<Vec<u8>>,
    oauth_bearer_token: Option<String>,
    platform_properties: BTreeMap<String, String>,
    thread_count: usize,
    store: Store,
    futures_timer_thread: resettable::Resettable<futures_timer::HelperThread>,
  ) -> CommandRunner {
    let env = Arc::new(grpcio::Environment::new(thread_count));
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

    CommandRunner {
      cache_key_gen_version,
      instance_name,
      authorization_header: oauth_bearer_token.map(|t| format!("Bearer {}", t)),
      platform_properties,
      channel,
      env,
      execution_client,
      operations_client,
      store,
      futures_timer_thread,
    }
  }

  fn call_option(&self) -> grpcio::CallOption {
    let mut call_option = grpcio::CallOption::default();
    if let Some(ref authorization_header) = self.authorization_header {
      let mut builder = grpcio::MetadataBuilder::with_capacity(1);
      builder
        .add_str("authorization", &authorization_header)
        .unwrap();
      call_option = call_option.headers(builder.build());
    }
    call_option
  }

  fn store_proto_locally<P: protobuf::Message>(
    &self,
    proto: &P,
  ) -> impl Future<Item = Digest, Error = String> {
    let store = self.store.clone();
    future::done(
      proto
        .write_to_bytes()
        .map_err(|e| format!("Error serializing proto {:?}", e)),
    )
    .and_then(move |command_bytes| store.store_file_bytes(Bytes::from(command_bytes), true))
    .map_err(|e| format!("Error saving proto to local store: {:?}", e))
  }

  fn extract_execute_response(
    &self,
    operation_or_status: OperationOrStatus,
    attempts: &mut ExecutionHistory,
  ) -> BoxFuture<FallibleExecuteProcessResult, ExecutionError> {
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
          let enqueued = timespec_from(metadata.get_queued_timestamp());
          let worker_start = timespec_from(metadata.get_worker_start_timestamp());
          let input_fetch_start = timespec_from(metadata.get_input_fetch_start_timestamp());
          let input_fetch_completed = timespec_from(metadata.get_input_fetch_completed_timestamp());
          let execution_start = timespec_from(metadata.get_execution_start_timestamp());
          let execution_completed = timespec_from(metadata.get_execution_completed_timestamp());
          let output_upload_start = timespec_from(metadata.get_output_upload_start_timestamp());
          let output_upload_completed =
            timespec_from(metadata.get_output_upload_completed_timestamp());

          match (worker_start - enqueued).to_std() {
            Ok(duration) => attempts.current_attempt.remote_queue = Some(duration),
            Err(err) => warn!("Got negative remote queue time: {}", err),
          }
          match (input_fetch_completed - input_fetch_start).to_std() {
            Ok(duration) => attempts.current_attempt.remote_input_fetch = Some(duration),
            Err(err) => warn!("Got negative remote input fetch time: {}", err),
          }
          match (execution_completed - execution_start).to_std() {
            Ok(duration) => attempts.current_attempt.remote_execution = Some(duration),
            Err(err) => warn!("Got negative remote execution time: {}", err),
          }
          match (output_upload_completed - output_upload_start).to_std() {
            Ok(duration) => attempts.current_attempt.remote_output_store = Some(duration),
            Err(err) => warn!("Got negative remote output store time: {}", err),
          }
          attempts.current_attempt.was_cache_hit = execute_response.cached_result;
        }

        let mut execution_attempts = std::mem::replace(&mut attempts.attempts, vec![]);
        execution_attempts.push(attempts.current_attempt);

        let status = execute_response.take_status();
        if grpcio::RpcStatusCode::from(status.get_code()) == grpcio::RpcStatusCode::Ok {
          return self
            .extract_stdout(&execute_response)
            .join(self.extract_stderr(&execute_response))
            .join(self.extract_output_files(&execute_response))
            .and_then(move |((stdout, stderr), output_directory)| {
              Ok(FallibleExecuteProcessResult {
                stdout: stdout,
                stderr: stderr,
                exit_code: execute_response.get_result().get_exit_code(),
                output_directory: output_directory,
                execution_attempts: execution_attempts,
              })
            })
            .to_boxed();
        }
        status
      }
      OperationOrStatus::Status(status) => status,
    };

    match grpcio::RpcStatusCode::from(status.get_code()) {
      grpcio::RpcStatusCode::Ok => unreachable!(),
      grpcio::RpcStatusCode::FailedPrecondition => {
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
      code => future::err(ExecutionError::Fatal(format!(
        "Error from remote execution: {:?}: {:?}",
        code,
        status.get_message()
      )))
      .to_boxed(),
    }
    .to_boxed()
  }

  fn extract_stdout(
    &self,
    execute_response: &bazel_protos::remote_execution::ExecuteResponse,
  ) -> BoxFuture<Bytes, ExecutionError> {
    if execute_response.get_result().has_stdout_digest() {
      let stdout_digest_result: Result<Digest, String> =
        execute_response.get_result().get_stdout_digest().into();
      let stdout_digest = try_future!(stdout_digest_result
        .map_err(|err| ExecutionError::Fatal(format!("Error extracting stdout: {}", err))));
      self
        .store
        .load_file_bytes_with(stdout_digest, |v| v)
        .map_err(move |error| {
          ExecutionError::Fatal(format!(
            "Error fetching stdout digest ({:?}): {:?}",
            stdout_digest, error
          ))
        })
        .and_then(move |maybe_value| {
          maybe_value.ok_or_else(|| {
            ExecutionError::Fatal(format!(
              "Couldn't find stdout digest ({:?}), when fetching.",
              stdout_digest
            ))
          })
        })
        .to_boxed()
    } else {
      let stdout_raw = Bytes::from(execute_response.get_result().get_stdout_raw());
      let stdout_copy = stdout_raw.clone();
      self
        .store
        .store_file_bytes(stdout_raw, true)
        .map_err(move |error| {
          ExecutionError::Fatal(format!("Error storing raw stdout: {:?}", error))
        })
        .map(|_| stdout_copy)
        .to_boxed()
    }
  }

  fn extract_stderr(
    &self,
    execute_response: &bazel_protos::remote_execution::ExecuteResponse,
  ) -> BoxFuture<Bytes, ExecutionError> {
    if execute_response.get_result().has_stderr_digest() {
      let stderr_digest_result: Result<Digest, String> =
        execute_response.get_result().get_stderr_digest().into();
      let stderr_digest = try_future!(stderr_digest_result
        .map_err(|err| ExecutionError::Fatal(format!("Error extracting stderr: {}", err))));
      self
        .store
        .load_file_bytes_with(stderr_digest, |v| v)
        .map_err(move |error| {
          ExecutionError::Fatal(format!(
            "Error fetching stderr digest ({:?}): {:?}",
            stderr_digest, error
          ))
        })
        .and_then(move |maybe_value| {
          maybe_value.ok_or_else(|| {
            ExecutionError::Fatal(format!(
              "Couldn't find stderr digest ({:?}), when fetching.",
              stderr_digest
            ))
          })
        })
        .to_boxed()
    } else {
      let stderr_raw = Bytes::from(execute_response.get_result().get_stderr_raw());
      let stderr_copy = stderr_raw.clone();
      self
        .store
        .store_file_bytes(stderr_raw, true)
        .map_err(move |error| {
          ExecutionError::Fatal(format!("Error storing raw stderr: {:?}", error))
        })
        .map(|_| stderr_copy)
        .to_boxed()
    }
  }

  fn extract_output_files(
    &self,
    execute_response: &bazel_protos::remote_execution::ExecuteResponse,
  ) -> BoxFuture<Digest, ExecutionError> {
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
      let digest_result: Result<Digest, String> = dir.get_tree_digest().into();
      let mut digest = future::done(digest_result).to_boxed();
      for component in dir.get_path().rsplit('/') {
        let component = component.to_owned();
        let store = self.store.clone();
        digest = digest
          .and_then(move |digest| {
            let mut directory = bazel_protos::remote_execution::Directory::new();
            directory.mut_directories().push({
              let mut node = bazel_protos::remote_execution::DirectoryNode::new();
              node.set_name(component);
              node.set_digest((&digest).into());
              node
            });
            store.record_directory(&directory, true)
          })
          .to_boxed();
      }
      directory_digests.push(digest.map_err(|err| {
        ExecutionError::Fatal(format!("Error saving remote output directory: {}", err))
      }));
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

    let path_stats = try_future!(path_stats_result.map_err(ExecutionError::Fatal));

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

    impl fs::StoreFileByDigest<String> for StoreOneOffRemoteDigest {
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

    let store = self.store.clone();
    fs::Snapshot::digest_from_path_stats(
      self.store.clone(),
      &StoreOneOffRemoteDigest::new(path_map),
      &path_stats,
    )
    .map_err(move |error| {
      ExecutionError::Fatal(format!(
        "Error when storing the output file directory info in the remote CAS: {:?}",
        error
      ))
    })
    .join(future::join_all(directory_digests))
    .and_then(|(files_digest, mut directory_digests)| {
      directory_digests.push(files_digest);
      fs::Snapshot::merge_directories(store, directory_digests).map_err(|err| {
        ExecutionError::Fatal(format!(
          "Error when merging output files and directories: {}",
          err
        ))
      })
    })
    .to_boxed()
  }
}

fn make_execute_request(
  req: &ExecuteProcessRequest,
  instance_name: &Option<String>,
  cache_key_gen_version: &Option<String>,
  mut platform_properties: BTreeMap<String, String>,
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
  for (ref name, ref value) in &req.env {
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
  if let Some(cache_key_gen_version) = cache_key_gen_version {
    let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
    env.set_name(CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_string());
    env.set_value(cache_key_gen_version.to_string());
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

  if req.jdk_home.is_some() {
    // Ideally, the JDK would be brought along as part of the input directory, but we don't
    // currently have support for that. Scoot supports this property, and will symlink .jdk to a
    // system-installed JDK https://github.com/twitter/scoot/pull/391 - we should probably come to
    // some kind of consensus across tools as to how this should work; RBE appears to work by
    // allowing you to specify a jdk-version platform property, and it will put a JDK at a
    // well-known path in the docker container you specify in which to run.
    platform_properties.insert("JDK_SYMLINK".to_owned(), ".jdk".to_owned());
  }

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
    execute_request.set_instance_name(instance_name.clone());
  }
  execute_request.set_action_digest((&digest(&action)?).into());

  Ok((action, command, execute_request))
}

fn format_error(error: &bazel_protos::status::Status) -> String {
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
    &grpcio::Error::RpcFailure(ref rs) if rs.status == grpcio::RpcStatusCode::Cancelled => {
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

fn digest(message: &dyn Message) -> Result<Digest, String> {
  let bytes = message.write_to_bytes().map_err(|e| format!("{:?}", e))?;

  let mut hasher = Sha256::default();
  hasher.input(&bytes);

  Ok(Digest(
    Fingerprint::from_bytes_unsafe(&hasher.fixed_result()),
    bytes.len(),
  ))
}

fn timespec_from(timestamp: &protobuf::well_known_types::Timestamp) -> time::Timespec {
  time::Timespec::new(timestamp.seconds, timestamp.nanos)
}

#[cfg(test)]
mod tests {
  use bazel_protos;
  use bytes::Bytes;
  use fs;
  use futures::Future;
  use grpcio;
  use hashing::{Digest, Fingerprint};
  use mock;
  use protobuf::{self, Message, ProtobufEnum};
  use tempfile::TempDir;
  use testutil::data::{TestData, TestDirectory};
  use testutil::{as_bytes, owned_string_vec};

  use super::super::CommandRunner as CommandRunnerTrait;
  use super::{
    CommandRunner, ExecuteProcessRequest, ExecutionError, ExecutionHistory,
    FallibleExecuteProcessResult,
  };
  use mock::execution_server::MockOperation;
  use std::collections::{BTreeMap, BTreeSet};
  use std::iter::{self, FromIterator};
  use std::ops::Sub;
  use std::path::PathBuf;
  use std::time::Duration;

  #[derive(Debug, PartialEq)]
  enum StdoutType {
    Raw(String),
    Digest(Digest),
  }

  #[derive(Debug, PartialEq)]
  enum StderrType {
    Raw(String),
    Digest(Digest),
  }

  #[test]
  fn make_execute_request() {
    let input_directory = TestDirectory::containing_roland();
    let req = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "yo"]),
      env: vec![("SOME".to_owned(), "value".to_owned())]
        .into_iter()
        .collect(),
      input_files: input_directory.digest(),
      // Intentionally poorly sorted:
      output_files: vec!["path/to/file", "other/file"]
        .into_iter()
        .map(PathBuf::from)
        .collect(),
      output_directories: vec!["directory/name"]
        .into_iter()
        .map(PathBuf::from)
        .collect(),
      timeout: Duration::from_millis(1000),
      description: "some description".to_owned(),
      jdk_home: None,
    };

    let mut want_command = bazel_protos::remote_execution::Command::new();
    want_command.mut_arguments().push("/bin/echo".to_owned());
    want_command.mut_arguments().push("yo".to_owned());
    want_command.mut_environment_variables().push({
      let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
      env.set_name("SOME".to_owned());
      env.set_value("value".to_owned());
      env
    });
    want_command
      .mut_output_files()
      .push("other/file".to_owned());
    want_command
      .mut_output_files()
      .push("path/to/file".to_owned());
    want_command
      .mut_output_directories()
      .push("directory/name".to_owned());

    let mut want_action = bazel_protos::remote_execution::Action::new();
    want_action.set_command_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "cc4ddd3085aaffbe0abce22f53b30edbb59896bb4a4f0d76219e48070cd0afe1",
        )
        .unwrap(),
        72,
      ))
        .into(),
    );
    want_action.set_input_root_digest((&input_directory.digest()).into());

    let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
    want_execute_request.set_action_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "844c929423444f3392e0dcc89ebf1febbfdf3a2e2fcab7567cc474705a5385e4",
        )
        .unwrap(),
        140,
      ))
        .into(),
    );

    assert_eq!(
      super::make_execute_request(&req, &None, &None, BTreeMap::new()),
      Ok((want_action, want_command, want_execute_request))
    );
  }

  #[test]
  fn make_execute_request_with_instance_name() {
    let input_directory = TestDirectory::containing_roland();
    let req = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "yo"]),
      env: vec![("SOME".to_owned(), "value".to_owned())]
        .into_iter()
        .collect(),
      input_files: input_directory.digest(),
      // Intentionally poorly sorted:
      output_files: vec!["path/to/file", "other/file"]
        .into_iter()
        .map(PathBuf::from)
        .collect(),
      output_directories: vec!["directory/name"]
        .into_iter()
        .map(PathBuf::from)
        .collect(),
      timeout: Duration::from_millis(1000),
      description: "some description".to_owned(),
      jdk_home: None,
    };

    let mut want_command = bazel_protos::remote_execution::Command::new();
    want_command.mut_arguments().push("/bin/echo".to_owned());
    want_command.mut_arguments().push("yo".to_owned());
    want_command.mut_environment_variables().push({
      let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
      env.set_name("SOME".to_owned());
      env.set_value("value".to_owned());
      env
    });
    want_command
      .mut_output_files()
      .push("other/file".to_owned());
    want_command
      .mut_output_files()
      .push("path/to/file".to_owned());
    want_command
      .mut_output_directories()
      .push("directory/name".to_owned());

    let mut want_action = bazel_protos::remote_execution::Action::new();
    want_action.set_command_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "cc4ddd3085aaffbe0abce22f53b30edbb59896bb4a4f0d76219e48070cd0afe1",
        )
        .unwrap(),
        72,
      ))
        .into(),
    );
    want_action.set_input_root_digest((&input_directory.digest()).into());

    let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
    want_execute_request.set_instance_name("dark-tower".to_owned());
    want_execute_request.set_action_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "844c929423444f3392e0dcc89ebf1febbfdf3a2e2fcab7567cc474705a5385e4",
        )
        .unwrap(),
        140,
      ))
        .into(),
    );

    assert_eq!(
      super::make_execute_request(&req, &Some("dark-tower".to_owned()), &None, BTreeMap::new()),
      Ok((want_action, want_command, want_execute_request))
    );
  }

  #[test]
  fn make_execute_request_with_cache_key_gen_version() {
    let input_directory = TestDirectory::containing_roland();
    let req = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "yo"]),
      env: vec![("SOME".to_owned(), "value".to_owned())]
        .into_iter()
        .collect(),
      input_files: input_directory.digest(),
      // Intentionally poorly sorted:
      output_files: vec!["path/to/file", "other/file"]
        .into_iter()
        .map(PathBuf::from)
        .collect(),
      output_directories: vec!["directory/name"]
        .into_iter()
        .map(PathBuf::from)
        .collect(),
      timeout: Duration::from_millis(1000),
      description: "some description".to_owned(),
      jdk_home: None,
    };

    let mut want_command = bazel_protos::remote_execution::Command::new();
    want_command.mut_arguments().push("/bin/echo".to_owned());
    want_command.mut_arguments().push("yo".to_owned());
    want_command.mut_environment_variables().push({
      let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
      env.set_name("SOME".to_owned());
      env.set_value("value".to_owned());
      env
    });
    want_command.mut_environment_variables().push({
      let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
      env.set_name(super::CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_owned());
      env.set_value("meep".to_owned());
      env
    });
    want_command
      .mut_output_files()
      .push("other/file".to_owned());
    want_command
      .mut_output_files()
      .push("path/to/file".to_owned());
    want_command
      .mut_output_directories()
      .push("directory/name".to_owned());

    let mut want_action = bazel_protos::remote_execution::Action::new();
    want_action.set_command_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "1a95e3482dd235593df73dc12b808ec7d922733a40d97d8233c1a32c8610a56d",
        )
        .unwrap(),
        109,
      ))
        .into(),
    );
    want_action.set_input_root_digest((&input_directory.digest()).into());

    let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
    want_execute_request.set_action_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "0ee5d4c8ac12513a87c8d949c6883ac533a264d30215126af71a9028c4ab6edf",
        )
        .unwrap(),
        140,
      ))
        .into(),
    );

    assert_eq!(
      super::make_execute_request(&req, &None, &Some("meep".to_owned()), BTreeMap::new()),
      Ok((want_action, want_command, want_execute_request))
    );
  }

  #[test]
  fn make_execute_request_with_jdk() {
    let input_directory = TestDirectory::containing_roland();
    let req = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "yo"]),
      env: BTreeMap::new(),
      input_files: input_directory.digest(),
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "some description".to_owned(),
      jdk_home: Some(PathBuf::from("/tmp")),
    };

    let mut want_command = bazel_protos::remote_execution::Command::new();
    want_command.mut_arguments().push("/bin/echo".to_owned());
    want_command.mut_arguments().push("yo".to_owned());
    want_command.mut_platform().mut_properties().push({
      let mut property = bazel_protos::remote_execution::Platform_Property::new();
      property.set_name("JDK_SYMLINK".to_owned());
      property.set_value(".jdk".to_owned());
      property
    });

    let mut want_action = bazel_protos::remote_execution::Action::new();
    want_action.set_command_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "f373f421b328ddeedfba63542845c0423d7730f428dd8e916ec6a38243c98448",
        )
        .unwrap(),
        38,
      ))
        .into(),
    );
    want_action.set_input_root_digest((&input_directory.digest()).into());

    let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
    want_execute_request.set_action_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "b1fb7179ce496995a4e3636544ec000dca1b951f1f6216493f6c7608dc4dd910",
        )
        .unwrap(),
        140,
      ))
        .into(),
    );

    assert_eq!(
      super::make_execute_request(&req, &None, &None, BTreeMap::new()),
      Ok((want_action, want_command, want_execute_request))
    );
  }

  #[test]
  fn make_execute_request_with_jdk_and_extra_platform_properties() {
    let input_directory = TestDirectory::containing_roland();
    let req = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "yo"]),
      env: BTreeMap::new(),
      input_files: input_directory.digest(),
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "some description".to_owned(),
      jdk_home: Some(PathBuf::from("/tmp")),
    };

    let mut want_command = bazel_protos::remote_execution::Command::new();
    want_command.mut_arguments().push("/bin/echo".to_owned());
    want_command.mut_arguments().push("yo".to_owned());
    want_command.mut_platform().mut_properties().push({
      let mut property = bazel_protos::remote_execution::Platform_Property::new();
      property.set_name("FIRST".to_owned());
      property.set_value("foo".to_owned());
      property
    });
    want_command.mut_platform().mut_properties().push({
      let mut property = bazel_protos::remote_execution::Platform_Property::new();
      property.set_name("JDK_SYMLINK".to_owned());
      property.set_value(".jdk".to_owned());
      property
    });
    want_command.mut_platform().mut_properties().push({
      let mut property = bazel_protos::remote_execution::Platform_Property::new();
      property.set_name("last".to_owned());
      property.set_value("bar".to_owned());
      property
    });

    let mut want_action = bazel_protos::remote_execution::Action::new();
    want_action.set_command_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "a809e7c54a105e7d98cc61558ac13ca3c05a5e1cb33326dfde189c72887dac29",
        )
        .unwrap(),
        65,
      ))
        .into(),
    );
    want_action.set_input_root_digest((&input_directory.digest()).into());

    let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
    want_execute_request.set_action_digest(
      (&Digest(
        Fingerprint::from_hex_string(
          "3d8d2a0282cb45b365b338f80ddab039dfa461dadde053e12bd5c3ab3329d928",
        )
        .unwrap(),
        140,
      ))
        .into(),
    );

    assert_eq!(
      super::make_execute_request(
        &req,
        &None,
        &None,
        vec![
          ("FIRST".to_owned(), "foo".to_owned()),
          ("last".to_owned(), "bar".to_owned())
        ]
        .into_iter()
        .collect()
      ),
      Ok((want_action, want_command, want_execute_request))
    );
  }

  #[test]
  fn server_rejecting_execute_request_gives_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        "wrong-command".to_string(),
        super::make_execute_request(
          &ExecuteProcessRequest {
            argv: owned_string_vec(&["/bin/echo", "-n", "bar"]),
            env: BTreeMap::new(),
            input_files: fs::EMPTY_DIGEST,
            output_files: BTreeSet::new(),
            output_directories: BTreeSet::new(),
            timeout: Duration::from_millis(1000),
            description: "wrong command".to_string(),
            jdk_home: None,
          },
          &None,
          &None,
          BTreeMap::new(),
        )
        .unwrap()
        .2,
        vec![],
      ))
    };

    let error = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");
    assert_eq!(
      error,
      "InvalidArgument: \"Did not expect this request\"".to_string()
    );
  }

  #[test]
  fn successful_execution_after_one_getoperation() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        ],
      ))
    };

    let result = run_command_remote(mock_server.address(), execute_request).unwrap();

    assert_eq!(
      result.without_execution_attempts(),
      FallibleExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      }
    );
  }

  #[test]
  fn extract_response_with_digest_stdout() {
    let op_name = "gimme-foo".to_string();
    let testdata = TestData::roland();
    let testdata_empty = TestData::empty();
    assert_eq!(
      extract_execute_response(
        make_successful_operation(
          &op_name,
          StdoutType::Digest(testdata.digest()),
          StderrType::Raw(testdata_empty.string()),
          0,
        )
        .op
        .unwrap()
        .unwrap()
      )
      .unwrap()
      .without_execution_attempts(),
      FallibleExecuteProcessResult {
        stdout: testdata.bytes(),
        stderr: testdata_empty.bytes(),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      }
    );
  }

  #[test]
  fn extract_response_with_digest_stderr() {
    let op_name = "gimme-foo".to_string();
    let testdata = TestData::roland();
    let testdata_empty = TestData::empty();
    assert_eq!(
      extract_execute_response(
        make_successful_operation(
          &op_name,
          StdoutType::Raw(testdata_empty.string()),
          StderrType::Digest(testdata.digest()),
          0,
        )
        .op
        .unwrap()
        .unwrap()
      )
      .unwrap()
      .without_execution_attempts(),
      FallibleExecuteProcessResult {
        stdout: testdata_empty.bytes(),
        stderr: testdata.bytes(),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      }
    );
  }

  #[test]
  fn ensure_inline_stdio_is_stored() {
    let mut runtime = tokio::runtime::Runtime::new().unwrap();

    let test_stdout = TestData::roland();
    let test_stderr = TestData::catnip();

    let mock_server = {
      let op_name = "cat".to_owned();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&echo_roland_request(), &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![make_successful_operation(
          &op_name.clone(),
          StdoutType::Raw(test_stdout.string()),
          StderrType::Raw(test_stderr.string()),
          0,
        )],
      ))
    };

    let store_dir = TempDir::new().unwrap();
    let store_dir_path = store_dir.path();

    let cas = mock::StubCAS::empty();
    let timer_thread = timer_thread();
    let store = fs::Store::with_remote(
      &store_dir_path,
      &[cas.address()],
      None,
      &None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      fs::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      timer_thread.with(|t| t.handle()),
    )
    .expect("Failed to make store");

    let cmd_runner = CommandRunner::new(
      &mock_server.address(),
      None,
      None,
      None,
      None,
      BTreeMap::new(),
      1,
      store,
      timer_thread,
    );
    let result = runtime
      .block_on(cmd_runner.run(echo_roland_request()))
      .unwrap();
    assert_eq!(
      result.without_execution_attempts(),
      FallibleExecuteProcessResult {
        stdout: test_stdout.bytes(),
        stderr: test_stderr.bytes(),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      }
    );

    let local_store = fs::Store::local_only(&store_dir_path).expect("Error creating local store");
    {
      assert_eq!(
        runtime
          .block_on(local_store.load_file_bytes_with(test_stdout.digest(), |v| v))
          .unwrap(),
        Some(test_stdout.bytes())
      );
      assert_eq!(
        runtime
          .block_on(local_store.load_file_bytes_with(test_stderr.digest(), |v| v))
          .unwrap(),
        Some(test_stderr.bytes())
      );
    }
  }

  #[test]
  fn successful_execution_after_four_getoperations() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        Vec::from_iter(
          iter::repeat(make_incomplete_operation(&op_name))
            .take(4)
            .chain(iter::once(make_successful_operation(
              &op_name,
              StdoutType::Raw("foo".to_owned()),
              StderrType::Raw("".to_owned()),
              0,
            ))),
        ),
      ))
    };

    let result = run_command_remote(mock_server.address(), execute_request).unwrap();

    assert_eq!(
      result.without_execution_attempts(),
      FallibleExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      }
    );
  }

  #[test]
  fn timeout_after_sufficiently_delayed_getoperations() {
    let request_timeout = Duration::new(4, 0);
    let delayed_operation_time = Duration::new(5, 0);

    let execute_request = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: request_timeout,
      description: "echo-a-foo".to_string(),
      jdk_home: None,
    };

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          make_delayed_incomplete_operation(&op_name, delayed_operation_time),
        ],
      ))
    };

    let error_msg = run_command_remote(mock_server.address(), execute_request)
      .expect_err("Timeout did not cause failure.");
    assert_contains(&error_msg, "Exceeded time out");
    assert_contains(&error_msg, "echo-a-foo");
  }

  #[test]
  fn retry_for_cancelled_channel() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          make_canceled_operation(Some(Duration::from_millis(100))),
          make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        ],
      ))
    };

    let result = run_command_remote(mock_server.address(), execute_request).unwrap();

    assert_eq!(
      result.without_execution_attempts(),
      FallibleExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      }
    );
  }

  #[test]
  fn bad_result_bytes() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          MockOperation::new({
            let mut op = bazel_protos::operations::Operation::new();
            op.set_name(op_name.clone());
            op.set_done(true);
            op.set_response({
              let mut response_wrapper = protobuf::well_known_types::Any::new();
              response_wrapper.set_type_url(format!(
                "type.googleapis.com/{}",
                bazel_protos::remote_execution::ExecuteResponse::new()
                  .descriptor()
                  .full_name()
              ));
              response_wrapper.set_value(vec![0x00, 0x00, 0x00]);
              response_wrapper
            });
            op
          }),
        ],
      ))
    };

    run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");
  }

  #[test]
  fn initial_response_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![MockOperation::new({
          let mut op = bazel_protos::operations::Operation::new();
          op.set_name(op_name.to_string());
          op.set_done(true);
          op.set_error({
            let mut error = bazel_protos::status::Status::new();
            error.set_code(bazel_protos::code::Code::INTERNAL.value());
            error.set_message("Something went wrong".to_string());
            error
          });
          op
        })],
      ))
    };

    let result = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");

    assert_eq!(result, "INTERNAL: Something went wrong");
  }

  #[test]
  fn getoperation_response_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          MockOperation::new({
            let mut op = bazel_protos::operations::Operation::new();
            op.set_name(op_name.to_string());
            op.set_done(true);
            op.set_error({
              let mut error = bazel_protos::status::Status::new();
              error.set_code(bazel_protos::code::Code::INTERNAL.value());
              error.set_message("Something went wrong".to_string());
              error
            });
            op
          }),
        ],
      ))
    };

    let result = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");

    assert_eq!(result, "INTERNAL: Something went wrong");
  }

  #[test]
  fn initial_response_missing_response_and_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![MockOperation::new({
          let mut op = bazel_protos::operations::Operation::new();
          op.set_name(op_name.to_string());
          op.set_done(true);
          op
        })],
      ))
    };

    let result = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");

    assert_eq!(result, "Operation finished but no response supplied");
  }

  #[test]
  fn getoperation_missing_response_and_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          MockOperation::new({
            let mut op = bazel_protos::operations::Operation::new();
            op.set_name(op_name.to_string());
            op.set_done(true);
            op
          }),
        ],
      ))
    };

    let result = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");

    assert_eq!(result, "Operation finished but no response supplied");
  }

  #[test]
  fn execute_missing_file_uploads_if_known() {
    let mut runtime = tokio::runtime::Runtime::new().unwrap();

    let roland = TestData::roland();

    let mock_server = {
      let op_name = "cat".to_owned();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&cat_roland_request(), &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          make_precondition_failure_operation(vec![missing_preconditionfailure_violation(
            &roland.digest(),
          )]),
          make_successful_operation(
            "cat2",
            StdoutType::Raw(roland.string()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        ],
      ))
    };

    let store_dir = TempDir::new().unwrap();
    let cas = mock::StubCAS::builder()
      .directory(&TestDirectory::containing_roland())
      .build();
    let timer_thread = timer_thread();
    let store = fs::Store::with_remote(
      store_dir,
      &[cas.address()],
      None,
      &None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      fs::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      timer_thread.with(|t| t.handle()),
    )
    .expect("Failed to make store");
    runtime
      .block_on(store.store_file_bytes(roland.bytes(), false))
      .expect("Saving file bytes to store");
    runtime
      .block_on(store.record_directory(&TestDirectory::containing_roland().directory(), false))
      .expect("Saving directory bytes to store");
    let command_runner = CommandRunner::new(
      &mock_server.address(),
      None,
      None,
      None,
      None,
      BTreeMap::new(),
      1,
      store,
      timer_thread,
    );

    let result = runtime
      .block_on(command_runner.run(cat_roland_request()))
      .unwrap();
    assert_eq!(
      result.without_execution_attempts(),
      FallibleExecuteProcessResult {
        stdout: roland.bytes(),
        stderr: Bytes::from(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      }
    );
    {
      let blobs = cas.blobs.lock();
      assert_eq!(blobs.get(&roland.fingerprint()), Some(&roland.bytes()));
    }
  }

  //#[test] // TODO: Unignore this test when the server can actually fail with status protos.
  // See https://github.com/pantsbuild/pants/issues/6597
  #[allow(dead_code)]
  fn execute_missing_file_uploads_if_known_status() {
    let roland = TestData::roland();

    let mock_server = {
      let op_name = "cat".to_owned();

      let status = grpcio::RpcStatus {
        status: grpcio::RpcStatusCode::FailedPrecondition,
        details: None,
        status_proto_bytes: Some(
          make_precondition_failure_status(vec![missing_preconditionfailure_violation(
            &roland.digest(),
          )])
          .write_to_bytes()
          .unwrap(),
        ),
      };

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&cat_roland_request(), &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        vec![
          //make_incomplete_operation(&op_name),
          MockOperation {
            op: Err(status),
            duration: None,
          },
          make_successful_operation(
            "cat2",
            StdoutType::Raw(roland.string()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        ],
      ))
    };

    let store_dir = TempDir::new().unwrap();
    let cas = mock::StubCAS::builder()
      .directory(&TestDirectory::containing_roland())
      .build();
    let timer_thread = timer_thread();
    let store = fs::Store::with_remote(
      store_dir,
      &[cas.address()],
      None,
      &None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      fs::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      timer_thread.with(|t| t.handle()),
    )
    .expect("Failed to make store");
    store
      .store_file_bytes(roland.bytes(), false)
      .wait()
      .expect("Saving file bytes to store");

    let result = CommandRunner::new(
      &mock_server.address(),
      None,
      None,
      None,
      None,
      BTreeMap::new(),
      1,
      store,
      timer_thread,
    )
    .run(cat_roland_request())
    .wait();
    assert_eq!(
      result,
      Ok(FallibleExecuteProcessResult {
        stdout: roland.bytes(),
        stderr: Bytes::from(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      })
    );
    {
      let blobs = cas.blobs.lock();
      assert_eq!(blobs.get(&roland.fingerprint()), Some(&roland.bytes()));
    }
  }

  #[test]
  fn execute_missing_file_errors_if_unknown() {
    let missing_digest = TestDirectory::containing_roland().digest();

    let mock_server = {
      let op_name = "cat".to_owned();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&cat_roland_request(), &None, &None, BTreeMap::new())
          .unwrap()
          .2,
        // We won't get as far as trying to run the operation, so don't expect any requests whose
        // responses we would need to stub.
        vec![],
      ))
    };

    let store_dir = TempDir::new().unwrap();
    let cas = mock::StubCAS::builder()
      .file(&TestData::roland())
      .directory(&TestDirectory::containing_roland())
      .build();
    let timer_thread = timer_thread();
    let store = fs::Store::with_remote(
      store_dir,
      &[cas.address()],
      None,
      &None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      fs::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      timer_thread.with(|t| t.handle()),
    )
    .expect("Failed to make store");

    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    let runner = CommandRunner::new(
      &mock_server.address(),
      None,
      None,
      None,
      None,
      BTreeMap::new(),
      1,
      store,
      timer_thread,
    );

    let error = runtime
      .block_on(runner.run(cat_roland_request()))
      .expect_err("Want error");
    assert_contains(&error, &format!("{}", missing_digest.0));
  }

  #[test]
  fn format_error_complete() {
    let mut error = bazel_protos::status::Status::new();
    error.set_code(bazel_protos::code::Code::CANCELLED.value());
    error.set_message("Oops, oh well!".to_string());
    assert_eq!(
      super::format_error(&error),
      "CANCELLED: Oops, oh well!".to_string()
    );
  }

  #[test]
  fn extract_execute_response_unknown_code() {
    let mut error = bazel_protos::status::Status::new();
    error.set_code(555);
    error.set_message("Oops, oh well!".to_string());
    assert_eq!(
      super::format_error(&error),
      "555: Oops, oh well!".to_string()
    );
  }

  #[test]
  fn extract_execute_response_success() {
    let want_result = FallibleExecuteProcessResult {
      stdout: as_bytes("roland"),
      stderr: Bytes::from("simba"),
      exit_code: 17,
      output_directory: TestDirectory::nested().digest(),
      execution_attempts: vec![],
    };

    let mut output_file = bazel_protos::remote_execution::OutputFile::new();
    output_file.set_path("cats/roland".into());
    output_file.set_digest((&TestData::roland().digest()).into());
    output_file.set_is_executable(false);
    let mut output_files = protobuf::RepeatedField::new();
    output_files.push(output_file);

    let mut operation = bazel_protos::operations::Operation::new();
    operation.set_name("cat".to_owned());
    operation.set_done(true);
    operation.set_response(make_any_proto(&{
      let mut response = bazel_protos::remote_execution::ExecuteResponse::new();
      response.set_result({
        let mut result = bazel_protos::remote_execution::ActionResult::new();
        result.set_exit_code(want_result.exit_code);
        result.set_stdout_raw(Bytes::from(want_result.stdout.clone()));
        result.set_stderr_raw(Bytes::from(want_result.stderr.clone()));
        result.set_output_files(output_files);
        result
      });
      response
    }));

    assert_eq!(
      extract_execute_response(operation)
        .unwrap()
        .without_execution_attempts(),
      want_result
    );
  }

  #[test]
  fn extract_execute_response_pending() {
    let operation_name = "cat".to_owned();
    let mut operation = bazel_protos::operations::Operation::new();
    operation.set_name(operation_name.clone());
    operation.set_done(false);

    assert_eq!(
      extract_execute_response(operation),
      Err(ExecutionError::NotFinished(operation_name))
    );
  }

  #[test]
  fn extract_execute_response_missing_digests() {
    let missing_files = vec![
      TestData::roland().digest(),
      TestDirectory::containing_roland().digest(),
    ];

    let missing = missing_files
      .iter()
      .map(missing_preconditionfailure_violation)
      .collect();

    let operation = make_precondition_failure_operation(missing)
      .op
      .unwrap()
      .unwrap();

    assert_eq!(
      extract_execute_response(operation),
      Err(ExecutionError::MissingDigests(missing_files))
    );
  }

  #[test]
  fn extract_execute_response_missing_other_things() {
    let missing = vec![
      missing_preconditionfailure_violation(&TestData::roland().digest()),
      {
        let mut violation = bazel_protos::error_details::PreconditionFailure_Violation::new();
        violation.set_field_type("MISSING".to_owned());
        violation.set_subject("monkeys".to_owned());
        violation
      },
    ];

    let operation = make_precondition_failure_operation(missing)
      .op
      .unwrap()
      .unwrap();

    match extract_execute_response(operation) {
      Err(ExecutionError::Fatal(err)) => assert_contains(&err, "monkeys"),
      other => assert!(false, "Want fatal error, got {:?}", other),
    };
  }

  #[test]
  fn extract_execute_response_other_failed_precondition() {
    let missing = vec![{
      let mut violation = bazel_protos::error_details::PreconditionFailure_Violation::new();
      violation.set_field_type("OUT_OF_CAPACITY".to_owned());
      violation
    }];

    let operation = make_precondition_failure_operation(missing)
      .op
      .unwrap()
      .unwrap();

    match extract_execute_response(operation) {
      Err(ExecutionError::Fatal(err)) => assert_contains(&err, "OUT_OF_CAPACITY"),
      other => assert!(false, "Want fatal error, got {:?}", other),
    };
  }

  #[test]
  fn extract_execute_response_missing_without_list() {
    let missing = vec![];

    let operation = make_precondition_failure_operation(missing)
      .op
      .unwrap()
      .unwrap();

    match extract_execute_response(operation) {
      Err(ExecutionError::Fatal(err)) => assert_contains(&err.to_lowercase(), "precondition"),
      other => assert!(false, "Want fatal error, got {:?}", other),
    };
  }

  #[test]
  fn extract_execute_response_other_status() {
    let mut operation = bazel_protos::operations::Operation::new();
    operation.set_name("cat".to_owned());
    operation.set_done(true);
    operation.set_response(make_any_proto(&{
      let mut response = bazel_protos::remote_execution::ExecuteResponse::new();
      response.set_status({
        let mut status = bazel_protos::status::Status::new();
        status.set_code(grpcio::RpcStatusCode::PermissionDenied as i32);
        status
      });
      response
    }));

    match extract_execute_response(operation) {
      Err(ExecutionError::Fatal(err)) => assert_contains(&err, "PermissionDenied"),
      other => assert!(false, "Want fatal error, got {:?}", other),
    };
  }

  #[test]
  fn digest_command() {
    let mut command = bazel_protos::remote_execution::Command::new();
    command.mut_arguments().push("/bin/echo".to_string());
    command.mut_arguments().push("foo".to_string());

    let mut env1 = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
    env1.set_name("A".to_string());
    env1.set_value("a".to_string());
    command.mut_environment_variables().push(env1);

    let mut env2 = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
    env2.set_name("B".to_string());
    env2.set_value("b".to_string());
    command.mut_environment_variables().push(env2);

    let digest = super::digest(&command).unwrap();

    assert_eq!(
      &digest.0.to_hex(),
      "a32cd427e5df6a998199266681692989f56c19cabd1cc637bdd56ae2e62619b4"
    );
    assert_eq!(digest.1, 32)
  }

  #[test]
  fn wait_between_request_1_retry() {
    // wait at least 500 milli for one retry
    {
      let execute_request = echo_foo_request();
      let mock_server = {
        let op_name = "gimme-foo".to_string();
        mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
            .unwrap()
            .2,
          vec![
            make_incomplete_operation(&op_name),
            make_successful_operation(
              &op_name,
              StdoutType::Raw("foo".to_owned()),
              StderrType::Raw("".to_owned()),
              0,
            ),
          ],
        ))
      };
      run_command_remote(mock_server.address(), execute_request).unwrap();

      let messages = mock_server.mock_responder.received_messages.lock();
      assert!(messages.len() == 2);
      assert!(
        messages
          .get(1)
          .unwrap()
          .received_at
          .sub(messages.get(0).unwrap().received_at)
          >= Duration::from_millis(500)
      );
    }
  }

  #[test]
  fn wait_between_request_3_retry() {
    // wait at least 500 + 1000 + 1500 = 3000 milli for 3 retries.
    {
      let execute_request = echo_foo_request();
      let mock_server = {
        let op_name = "gimme-foo".to_string();
        mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request, &None, &None, BTreeMap::new())
            .unwrap()
            .2,
          vec![
            make_incomplete_operation(&op_name),
            make_incomplete_operation(&op_name),
            make_incomplete_operation(&op_name),
            make_successful_operation(
              &op_name,
              StdoutType::Raw("foo".to_owned()),
              StderrType::Raw("".to_owned()),
              0,
            ),
          ],
        ))
      };
      run_command_remote(mock_server.address(), execute_request).unwrap();

      let messages = mock_server.mock_responder.received_messages.lock();
      assert!(messages.len() == 4);
      assert!(
        messages
          .get(1)
          .unwrap()
          .received_at
          .sub(messages.get(0).unwrap().received_at)
          >= Duration::from_millis(500)
      );
      assert!(
        messages
          .get(2)
          .unwrap()
          .received_at
          .sub(messages.get(1).unwrap().received_at)
          >= Duration::from_millis(1000)
      );
      assert!(
        messages
          .get(3)
          .unwrap()
          .received_at
          .sub(messages.get(2).unwrap().received_at)
          >= Duration::from_millis(1500)
      );
    }
  }

  #[test]
  fn extract_output_files_from_response_one_file() {
    let mut output_file = bazel_protos::remote_execution::OutputFile::new();
    output_file.set_path("roland".into());
    output_file.set_digest((&TestData::roland().digest()).into());
    output_file.set_is_executable(false);
    let mut output_files = protobuf::RepeatedField::new();
    output_files.push(output_file);

    let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
    execute_response.set_result({
      let mut result = bazel_protos::remote_execution::ActionResult::new();
      result.set_exit_code(0);
      result.set_output_files(output_files);
      result
    });

    assert_eq!(
      extract_output_files_from_response(&execute_response),
      Ok(TestDirectory::containing_roland().digest())
    )
  }

  #[test]
  fn extract_output_files_from_response_two_files_not_nested() {
    let mut output_file_1 = bazel_protos::remote_execution::OutputFile::new();
    output_file_1.set_path("roland".into());
    output_file_1.set_digest((&TestData::roland().digest()).into());
    output_file_1.set_is_executable(false);

    let mut output_file_2 = bazel_protos::remote_execution::OutputFile::new();
    output_file_2.set_path("treats".into());
    output_file_2.set_digest((&TestData::catnip().digest()).into());
    output_file_2.set_is_executable(false);
    let mut output_files = protobuf::RepeatedField::new();
    output_files.push(output_file_1);
    output_files.push(output_file_2);

    let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
    execute_response.set_result({
      let mut result = bazel_protos::remote_execution::ActionResult::new();
      result.set_exit_code(0);
      result.set_output_files(output_files);
      result
    });

    assert_eq!(
      extract_output_files_from_response(&execute_response),
      Ok(TestDirectory::containing_roland_and_treats().digest())
    )
  }

  #[test]
  fn extract_output_files_from_response_two_files_nested() {
    let mut output_file_1 = bazel_protos::remote_execution::OutputFile::new();
    output_file_1.set_path("cats/roland".into());
    output_file_1.set_digest((&TestData::roland().digest()).into());
    output_file_1.set_is_executable(false);

    let mut output_file_2 = bazel_protos::remote_execution::OutputFile::new();
    output_file_2.set_path("treats".into());
    output_file_2.set_digest((&TestData::catnip().digest()).into());
    output_file_2.set_is_executable(false);
    let mut output_files = protobuf::RepeatedField::new();
    output_files.push(output_file_1);
    output_files.push(output_file_2);

    let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
    execute_response.set_result({
      let mut result = bazel_protos::remote_execution::ActionResult::new();
      result.set_exit_code(0);
      result.set_output_files(output_files);
      result
    });

    assert_eq!(
      extract_output_files_from_response(&execute_response),
      Ok(TestDirectory::recursive().digest())
    )
  }

  #[test]
  fn extract_output_files_from_response_just_directory() {
    let mut output_directory = bazel_protos::remote_execution::OutputDirectory::new();
    output_directory.set_path("cats".into());
    output_directory.set_tree_digest((&TestDirectory::containing_roland().digest()).into());
    let mut output_directories = protobuf::RepeatedField::new();
    output_directories.push(output_directory);

    let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
    execute_response.set_result({
      let mut result = bazel_protos::remote_execution::ActionResult::new();
      result.set_exit_code(0);
      result.set_output_directories(output_directories);
      result
    });

    assert_eq!(
      extract_output_files_from_response(&execute_response),
      Ok(TestDirectory::nested().digest())
    )
  }

  #[test]
  fn extract_output_files_from_response_directories_and_files() {
    // /catnip
    // /pets/cats/roland
    // /pets/dogs/robin

    let mut output_directories = protobuf::RepeatedField::new();
    output_directories.push({
      let mut output_directory = bazel_protos::remote_execution::OutputDirectory::new();
      output_directory.set_path("pets/cats".into());
      output_directory.set_tree_digest((&TestDirectory::containing_roland().digest()).into());
      output_directory
    });
    output_directories.push({
      let mut output_directory = bazel_protos::remote_execution::OutputDirectory::new();
      output_directory.set_path("pets/dogs".into());
      output_directory.set_tree_digest((&TestDirectory::containing_robin().digest()).into());
      output_directory
    });

    let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
    execute_response.set_result({
      let mut result = bazel_protos::remote_execution::ActionResult::new();
      result.set_exit_code(0);
      result.set_output_directories(output_directories);
      result.set_output_files({
        let mut output_files = protobuf::RepeatedField::new();
        output_files.push({
          let mut output_file = bazel_protos::remote_execution::OutputFile::new();
          output_file.set_path("treats".into());
          output_file.set_digest((&TestData::catnip().digest()).into());
          output_file
        });
        output_files
      });
      result
    });

    assert_eq!(
      extract_output_files_from_response(&execute_response),
      Ok(Digest(
        Fingerprint::from_hex_string(
          "639b4b84bb58a9353d49df8122e7987baf038efe54ed035e67910846c865b1e2"
        )
        .unwrap(),
        159
      ))
    )
  }

  fn echo_foo_request() -> ExecuteProcessRequest {
    ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(5000),
      description: "echo a foo".to_string(),
      jdk_home: None,
    }
  }

  fn make_canceled_operation(duration: Option<Duration>) -> MockOperation {
    MockOperation {
      op: Ok(None),
      duration,
    }
  }

  fn make_incomplete_operation(operation_name: &str) -> MockOperation {
    let mut op = bazel_protos::operations::Operation::new();
    op.set_name(operation_name.to_string());
    op.set_done(false);
    MockOperation::new(op)
  }

  fn make_delayed_incomplete_operation(operation_name: &str, delay: Duration) -> MockOperation {
    let mut op = bazel_protos::operations::Operation::new();
    op.set_name(operation_name.to_string());
    op.set_done(false);
    MockOperation {
      op: Ok(Some(op)),
      duration: Some(delay),
    }
  }

  fn make_successful_operation(
    operation_name: &str,
    stdout: StdoutType,
    stderr: StderrType,
    exit_code: i32,
  ) -> MockOperation {
    let mut op = bazel_protos::operations::Operation::new();
    op.set_name(operation_name.to_string());
    op.set_done(true);
    op.set_response({
      let mut response_proto = bazel_protos::remote_execution::ExecuteResponse::new();
      response_proto.set_result({
        let mut action_result = bazel_protos::remote_execution::ActionResult::new();
        match stdout {
          StdoutType::Raw(stdout_raw) => {
            action_result.set_stdout_raw(Bytes::from(stdout_raw));
          }
          StdoutType::Digest(stdout_digest) => {
            action_result.set_stdout_digest((&stdout_digest).into());
          }
        }
        match stderr {
          StderrType::Raw(stderr_raw) => {
            action_result.set_stderr_raw(Bytes::from(stderr_raw));
          }
          StderrType::Digest(stderr_digest) => {
            action_result.set_stderr_digest((&stderr_digest).into());
          }
        }
        action_result.set_exit_code(exit_code);
        action_result
      });

      let mut response_wrapper = protobuf::well_known_types::Any::new();
      response_wrapper.set_type_url(format!(
        "type.googleapis.com/{}",
        response_proto.descriptor().full_name()
      ));
      let response_proto_bytes = response_proto.write_to_bytes().unwrap();
      response_wrapper.set_value(response_proto_bytes);
      response_wrapper
    });
    MockOperation::new(op)
  }

  fn make_precondition_failure_operation(
    violations: Vec<bazel_protos::error_details::PreconditionFailure_Violation>,
  ) -> MockOperation {
    let mut operation = bazel_protos::operations::Operation::new();
    operation.set_name("cat".to_owned());
    operation.set_done(true);
    operation.set_response(make_any_proto(&{
      let mut response = bazel_protos::remote_execution::ExecuteResponse::new();
      response.set_status(make_precondition_failure_status(violations));
      response
    }));
    MockOperation::new(operation)
  }

  fn make_precondition_failure_status(
    violations: Vec<bazel_protos::error_details::PreconditionFailure_Violation>,
  ) -> bazel_protos::status::Status {
    let mut status = bazel_protos::status::Status::new();
    status.set_code(grpcio::RpcStatusCode::FailedPrecondition as i32);
    status.mut_details().push(make_any_proto(&{
      let mut precondition_failure = bazel_protos::error_details::PreconditionFailure::new();
      for violation in violations.into_iter() {
        precondition_failure.mut_violations().push(violation);
      }
      precondition_failure
    }));
    status
  }

  fn run_command_remote(
    address: String,
    request: ExecuteProcessRequest,
  ) -> Result<FallibleExecuteProcessResult, String> {
    let cas = mock::StubCAS::builder()
      .file(&TestData::roland())
      .directory(&TestDirectory::containing_roland())
      .build();
    let command_runner = create_command_runner(address, &cas);
    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    runtime.block_on(command_runner.run(request))
  }

  fn create_command_runner(address: String, cas: &mock::StubCAS) -> CommandRunner {
    let store_dir = TempDir::new().unwrap();
    let timer_thread = timer_thread();
    let store = fs::Store::with_remote(
      store_dir,
      &[cas.address()],
      None,
      &None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      fs::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      timer_thread.with(|t| t.handle()),
    )
    .expect("Failed to make store");

    CommandRunner::new(
      &address,
      None,
      None,
      None,
      None,
      BTreeMap::new(),
      1,
      store,
      timer_thread,
    )
  }

  fn timer_thread() -> resettable::Resettable<futures_timer::HelperThread> {
    resettable::Resettable::new(|| futures_timer::HelperThread::new().unwrap())
  }

  fn extract_execute_response(
    operation: bazel_protos::operations::Operation,
  ) -> Result<FallibleExecuteProcessResult, ExecutionError> {
    let cas = mock::StubCAS::builder()
      .file(&TestData::roland())
      .directory(&TestDirectory::containing_roland())
      .build();
    let command_runner = create_command_runner("".to_owned(), &cas);

    let mut runtime = tokio::runtime::Runtime::new().unwrap();

    runtime.block_on(command_runner.extract_execute_response(
      super::OperationOrStatus::Operation(operation),
      &mut ExecutionHistory::default(),
    ))
  }

  fn extract_output_files_from_response(
    execute_response: &bazel_protos::remote_execution::ExecuteResponse,
  ) -> Result<Digest, ExecutionError> {
    let cas = mock::StubCAS::builder()
      .file(&TestData::roland())
      .directory(&TestDirectory::containing_roland())
      .build();
    let command_runner = create_command_runner("".to_owned(), &cas);

    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    runtime.block_on(command_runner.extract_output_files(&execute_response))
  }

  fn make_any_proto(message: &dyn Message) -> protobuf::well_known_types::Any {
    let mut any = protobuf::well_known_types::Any::new();
    any.set_type_url(format!(
      "type.googleapis.com/{}",
      message.descriptor().full_name()
    ));
    any.set_value(message.write_to_bytes().expect("Error serializing proto"));
    any
  }

  fn missing_preconditionfailure_violation(
    digest: &Digest,
  ) -> bazel_protos::error_details::PreconditionFailure_Violation {
    {
      let mut violation = bazel_protos::error_details::PreconditionFailure_Violation::new();
      violation.set_field_type("MISSING".to_owned());
      violation.set_subject(format!("blobs/{}/{}", digest.0, digest.1));
      violation
    }
  }

  fn assert_contains(haystack: &str, needle: &str) {
    assert!(
      haystack.contains(needle),
      "{:?} should contain {:?}",
      haystack,
      needle
    )
  }

  fn cat_roland_request() -> ExecuteProcessRequest {
    ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/cat", "roland"]),
      env: BTreeMap::new(),
      input_files: TestDirectory::containing_roland().digest(),
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "cat a roland".to_string(),
      jdk_home: None,
    }
  }

  fn echo_roland_request() -> ExecuteProcessRequest {
    ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "meoooow"]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "unleash a roaring meow".to_string(),
      jdk_home: None,
    }
  }
}
