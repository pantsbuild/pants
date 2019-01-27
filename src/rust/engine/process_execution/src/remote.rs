use std::time::{Duration, Instant};

use bazel_protos;
use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use fs::{self, Store};
use futures::{future, Future, Stream};
use futures_timer::Delay;
use hashing::{Digest, Fingerprint};
use log::{debug, trace, warn};
use parking_lot::Mutex;
use prost::Message;
use protobuf::{self, Message as GrpcioMessage, ProtobufEnum};
use time;

use super::{
  BazelProtosProcessExecutionCodec, CacheableExecuteProcessRequest, CacheableExecuteProcessResult,
  ExecuteProcessRequest, ExecutionStats, FallibleExecuteProcessResult,
  SerializableProcessExecutionCodec,
};
use std;
use std::cmp::min;

use std::net::SocketAddr;
use std::net::ToSocketAddrs;
use tokio::executor::DefaultExecutor;
use tokio::net::tcp::{ConnectFuture, TcpStream};
use tower_grpc::Request;
use tower_h2::client;
use tower_util::MakeService;

#[derive(Debug)]
enum OperationOrStatus {
  Operation(bazel_protos::google::longrunning::Operation),
  Status(bazel_protos::google::rpc::Status),
}

type Connection = tower_http::add_origin::AddOrigin<
  tower_h2::client::Connection<tokio::net::tcp::TcpStream, DefaultExecutor, tower_grpc::BoxBody>,
>;

struct Clients {
  execution_client:
    Mutex<bazel_protos::build::bazel::remote::execution::v2::client::Execution<Connection>>,
  operations_client: Mutex<bazel_protos::google::longrunning::client::Operations<Connection>>,
}

#[derive(Clone)]
#[allow(clippy::type_complexity)]
pub struct CommandRunner {
  cache_key_gen_version: Option<String>,
  instance_name: Option<String>,
  authorization_header: Option<String>,
  clients: futures::future::Shared<BoxFuture<Clients, String>>,
  store: Store,
  futures_timer_thread: resettable::Resettable<futures_timer::HelperThread>,
  process_execution_codec: BazelProtosProcessExecutionCodecV2,
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
    execute_request: bazel_protos::build::bazel::remote::execution::v2::ExecuteRequest,
  ) -> impl Future<Item = OperationOrStatus, Error = String> {
    let command_runner = self.clone();
    self
      .clients
      .clone()
      .map_err(|err| format!("Error getting execution_client: {}", err))
      .and_then(move |clients| {
        clients
          .execution_client
          .lock()
          .execute(command_runner.make_request(execute_request))
          .map_err(towergrpcerror_to_string)
          .and_then(|response_stream| {
            response_stream
              .into_inner()
              .take(1)
              .into_future()
              .map_err(|err| {
                format!(
                  "Error getting response from remote process execution {:?}",
                  err
                )
              })
              .and_then(|(resp, stream)| {
                std::mem::drop(stream);
                resp.ok_or_else(|| "Didn't get response from remote process execution".to_owned())
              })
              .map(OperationOrStatus::Operation)
          })
      })
  }
}

#[derive(Clone)]
pub struct BazelProcessExecutionRequestV2 {
  action: bazel_protos::remote_execution::Action,
  command: bazel_protos::remote_execution::Command,
  execute_request: bazel_protos::build::bazel::remote::execution::v2::ExecuteRequest,
}

#[derive(Clone)]
pub struct BazelProtosProcessExecutionCodecV2 {
  inner: BazelProtosProcessExecutionCodec,
  instance_name: Option<String>,
}

impl BazelProtosProcessExecutionCodecV2 {
  fn new(store: fs::Store, instance_name: Option<String>) -> Self {
    let inner = BazelProtosProcessExecutionCodec::new(store);
    BazelProtosProcessExecutionCodecV2 {
      inner,
      instance_name,
    }
  }

  fn convert_digest(
    digest: bazel_protos::build::bazel::remote::execution::v2::Digest,
  ) -> bazel_protos::remote_execution::Digest {
    let mut resulting_digest = bazel_protos::remote_execution::Digest::new();
    resulting_digest.set_hash(digest.hash);
    resulting_digest.set_size_bytes(digest.size_bytes);
    resulting_digest
  }

  fn convert_output_file(
    output_file: bazel_protos::build::bazel::remote::execution::v2::OutputFile,
  ) -> bazel_protos::remote_execution::OutputFile {
    let mut resulting_output_file = bazel_protos::remote_execution::OutputFile::new();
    resulting_output_file.set_path(output_file.path);
    if let Some(digest) = output_file.digest.map(Self::convert_digest) {
      resulting_output_file.set_digest(digest);
    }
    resulting_output_file.set_is_executable(output_file.is_executable);
    resulting_output_file
  }

  fn convert_output_directory(
    output_dir: bazel_protos::build::bazel::remote::execution::v2::OutputDirectory,
  ) -> bazel_protos::remote_execution::OutputDirectory {
    let mut resulting_output_dir = bazel_protos::remote_execution::OutputDirectory::new();
    resulting_output_dir.set_path(output_dir.path);
    if let Some(digest) = output_dir.tree_digest.map(Self::convert_digest) {
      resulting_output_dir.set_tree_digest(digest);
    }
    resulting_output_dir
  }

  fn convert_action_result(
    action_result: bazel_protos::build::bazel::remote::execution::v2::ActionResult,
  ) -> bazel_protos::remote_execution::ActionResult {
    let mut resulting_action_result = bazel_protos::remote_execution::ActionResult::new();
    resulting_action_result.set_output_files(protobuf::RepeatedField::from_vec(
      action_result
        .output_files
        .iter()
        .cloned()
        .map(Self::convert_output_file)
        .collect::<Vec<_>>(),
    ));
    resulting_action_result.set_output_directories(protobuf::RepeatedField::from_vec(
      action_result
        .output_directories
        .iter()
        .cloned()
        .map(Self::convert_output_directory)
        .collect(),
    ));
    resulting_action_result.set_exit_code(action_result.exit_code);
    resulting_action_result.set_stdout_raw(Bytes::from(action_result.stdout_raw));
    if let Some(digest) = action_result.stdout_digest.map(Self::convert_digest) {
      resulting_action_result.set_stdout_digest(digest);
    }
    resulting_action_result.set_stderr_raw(Bytes::from(action_result.stderr_raw));
    if let Some(digest) = action_result.stderr_digest.map(Self::convert_digest) {
      resulting_action_result.set_stderr_digest(digest);
    }
    // TODO: resulting_action_result.set_execution_metadata();
    resulting_action_result
  }
}

impl
  SerializableProcessExecutionCodec<
    CacheableExecuteProcessRequest,
    BazelProcessExecutionRequestV2,
    CacheableExecuteProcessResult,
    bazel_protos::build::bazel::remote::execution::v2::ActionResult,
    String,
  > for BazelProtosProcessExecutionCodecV2
{
  fn convert_request(
    &self,
    req: CacheableExecuteProcessRequest,
  ) -> Result<BazelProcessExecutionRequestV2, String> {
    let (action, command) = BazelProtosProcessExecutionCodec::make_action_with_command(req)?;
    let execute_request = bazel_protos::build::bazel::remote::execution::v2::ExecuteRequest {
      action_digest: Some((&BazelProtosProcessExecutionCodec::digest_message(&action)?).into()),
      skip_cache_lookup: false,
      instance_name: self.instance_name.clone().unwrap_or_default(),
      execution_policy: None,
      results_cache_policy: None,
    };
    Ok(BazelProcessExecutionRequestV2 {
      action,
      command,
      execute_request,
    })
  }

  fn convert_response(
    &self,
    _res: CacheableExecuteProcessResult,
  ) -> Result<bazel_protos::build::bazel::remote::execution::v2::ActionResult, String> {
    panic!("converting from a cacheable process request to a v2 ActionResult is not yet supported");
  }

  fn extract_response(
    &self,
    serializable_response: bazel_protos::build::bazel::remote::execution::v2::ActionResult,
  ) -> BoxFuture<CacheableExecuteProcessResult, String> {
    let action_result_v1 = Self::convert_action_result(serializable_response);
    self.inner.extract_response(action_result_v1)
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
    let clients = self.clients.clone();

    let store = self.store.clone();
    let cacheable_execute_process_request =
      CacheableExecuteProcessRequest::new(req.clone(), self.cache_key_gen_version.clone());
    let execute_request_result = self
      .process_execution_codec
      .convert_request(cacheable_execute_process_request);

    let ExecuteProcessRequest {
      description,
      timeout,
      input_files,
      ..
    } = req;

    let description2 = description.clone();

    match execute_request_result {
      Ok(BazelProcessExecutionRequestV2 {
        action,
        command,
        execute_request,
      }) => {
        let command_runner = self.clone();
        let command_runner2 = self.clone();
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
              .oneshot_execute(execute_request)
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
                let clients = clients.clone();
                let command_runner2 = command_runner2.clone();
                let command_runner3 = command_runner2.clone();
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
                            .oneshot_execute(execute_request)
                            .join(future::ok(history))
                        })
                        // Reset `iter_num` on `MissingDigests`
                        .map(|(operation, history)| future::Loop::Continue((history, operation, 0)))
                        .to_boxed()
                    }
                    ExecutionError::NotFinished(operation_name) => {
                      let operation_name2 = operation_name.clone();
                      let operation_request =
                        bazel_protos::google::longrunning::GetOperationRequest {
                          name: operation_name.clone(),
                        };

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
                          futures_timer_thread.with(|thread| thread.handle()),
                        )
                        .map_err(move |e| {
                          format!(
                            "Future-Delay errored at operation result polling for {}, {}: {}",
                            operation_name, description, e
                          )
                        })
                        .and_then(move |_| {
                          clients
                            .map_err(|err| format!("{}", err))
                            .and_then(move |clients| {
                              clients
                                .operations_client
                                .lock()
                                .get_operation(command_runner3.make_request(operation_request))
                                .map(|r| r.into_inner())
                                .or_else(move |err| {
                                  rpcerror_recover_cancelled(operation_name2, err)
                                })
                                .map_err(towergrpcerror_to_string)
                            })
                            .map(OperationOrStatus::Operation)
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
    oauth_bearer_token: Option<String>,
    store: Store,
    futures_timer_thread: resettable::Resettable<futures_timer::HelperThread>,
  ) -> Result<CommandRunner, String> {
    struct Dst(SocketAddr);

    impl tokio_connect::Connect for Dst {
      type Connected = TcpStream;
      type Error = ::std::io::Error;
      type Future = ConnectFuture;

      fn connect(&self) -> Self::Future {
        TcpStream::connect(&self.0)
      }
    }

    // TODO: Support https
    let uri: http::Uri = format!("http://{}", address)
      .parse()
      .map_err(|err| format!("Failed to parse remote server address URL: {}", err))?;
    let socket_addr = address
      .to_socket_addrs()
      .map_err(|err| format!("Failed to resolve remote socket address URL: {}", err))?
      .next()
      .ok_or_else(|| "Remote server address resolved to no addresses".to_owned())?;
    let conn = client::Connect::new(
      Dst(socket_addr),
      h2::client::Builder::default(),
      DefaultExecutor::current(),
    )
    .make_service(())
    .map_err(|err| format!("Error connecting to remote execution server: {}", err))
    .and_then(move |conn| {
      tower_http::add_origin::Builder::new()
        .uri(uri)
        .build(conn)
        .map_err(|err| {
          format!(
            "Failed to add origin for remote execution server: {:?}",
            err
          )
        })
        .map(Mutex::new)
    });
    let clients = conn
      .map(|conn| {
        let conn = conn.lock();
        let execution_client = Mutex::new(
          bazel_protos::build::bazel::remote::execution::v2::client::Execution::new(conn.clone()),
        );
        let operations_client = Mutex::new(
          bazel_protos::google::longrunning::client::Operations::new(conn.clone()),
        );
        Clients {
          execution_client,
          operations_client,
        }
      })
      .to_boxed()
      .shared();
    Ok(CommandRunner {
      cache_key_gen_version,
      // TODO: this may be able to be removed!
      instance_name: instance_name.clone(),
      authorization_header: oauth_bearer_token.map(|t| format!("Bearer {}", t)),
      clients,
      store: store.clone(),
      futures_timer_thread,
      process_execution_codec: BazelProtosProcessExecutionCodecV2::new(store, instance_name),
    })
  }

  fn make_request<T>(&self, message: T) -> Request<T> {
    let mut request = Request::new(message);
    if let Some(ref authorization_header) = self.authorization_header {
      request
        .metadata_mut()
        .insert("authorization", authorization_header.parse().unwrap());
    }
    request
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
      OperationOrStatus::Operation(operation) => {
        if !operation.done {
          return future::err(ExecutionError::NotFinished(operation.name)).to_boxed();
        }
        let execute_response = if let Some(result) = operation.result {
          match result {
            bazel_protos::google::longrunning::operation::Result::Error(ref status) => {
              return future::err(ExecutionError::Fatal(format_error(status))).to_boxed();
            }
            bazel_protos::google::longrunning::operation::Result::Response(ref any) => try_future!(
              bazel_protos::build::bazel::remote::execution::v2::ExecuteResponse::decode(
                &any.value
              )
              .map_err(|e| ExecutionError::Fatal(format!("Invalid ExecuteResponse: {:?}", e)))
            ),
          }
        } else {
          return future::err(ExecutionError::Fatal(
            "Operation finished but no response supplied".to_string(),
          ))
          .to_boxed();
        };

        trace!("Got (nested) execute response: {:?}", execute_response);

        if let Some(ref result) = execute_response.result {
          if let Some(ref metadata) = result.execution_metadata {
            let enqueued = timespec_from(&metadata.queued_timestamp);
            let worker_start = timespec_from(&metadata.worker_start_timestamp);
            let input_fetch_start = timespec_from(&metadata.input_fetch_start_timestamp);
            let input_fetch_completed = timespec_from(&metadata.input_fetch_completed_timestamp);
            let execution_start = timespec_from(&metadata.execution_start_timestamp);
            let execution_completed = timespec_from(&metadata.execution_completed_timestamp);
            let output_upload_start = timespec_from(&metadata.output_upload_start_timestamp);
            let output_upload_completed =
              timespec_from(&metadata.output_upload_completed_timestamp);

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
        }

        let mut execution_attempts = std::mem::replace(&mut attempts.attempts, vec![]);
        execution_attempts.push(attempts.current_attempt);

        let maybe_result = execute_response.result;

        let status = execute_response
          .status
          .unwrap_or_else(|| bazel_protos::google::rpc::Status {
            code: bazel_protos::google::rpc::Code::Ok.into(),
            message: String::new(),
            details: vec![],
          });
        if status.code == bazel_protos::google::rpc::Code::Ok.into() {
          if let Some(result) = maybe_result {
            return self
              .process_execution_codec
              .extract_response(result.clone())
              .map(|cacheable_result| cacheable_result.with_execution_attempts(execution_attempts))
              .map_err(move |err| {
                ExecutionError::Fatal(format!(
                  "error deocding process result {:?}: {:?}",
                  result, err
                ))
              })
              .to_boxed();
          } else {
            return futures::future::err(ExecutionError::Fatal(
              "No result found on ExecuteResponse".to_owned(),
            ))
            .to_boxed();
          }
        }
        status
      }
      OperationOrStatus::Status(status) => status,
    };

    match bazel_protos::code_from_i32(status.code) {
      bazel_protos::google::rpc::Code::Ok => unreachable!(),
      bazel_protos::google::rpc::Code::FailedPrecondition => {
        if status.details.len() != 1 {
          return future::err(ExecutionError::Fatal(format!(
            "Received multiple details in FailedPrecondition ExecuteResponse's status field: {:?}",
            status.details
          )))
          .to_boxed();
        }
        let details = &status.details[0];
        let mut precondition_failure = bazel_protos::error_details::PreconditionFailure::new();
        if details.type_url
          != format!(
            "type.googleapis.com/{}",
            precondition_failure.descriptor().full_name()
          )
        {
          return future::err(ExecutionError::Fatal(format!(
            "Received FailedPrecondition, but didn't know how to resolve it: {},\
             protobuf type {}",
            status.message, details.type_url
          )))
          .to_boxed();
        }
        try_future!(precondition_failure
          .merge_from_bytes(&details.value)
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
          let digest =
            Digest(
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
        code, status.message
      )))
      .to_boxed(),
    }
    .to_boxed()
  }
}

fn format_error(error: &bazel_protos::google::rpc::Status) -> String {
  let error_code_enum = bazel_protos::code::Code::from_i32(error.code);
  let error_code = match error_code_enum {
    Some(x) => format!("{:?}", x),
    None => format!("{:?}", error.code),
  };
  format!("{}: {}", error_code, error.message)
}

///
/// If the given operation represents a cancelled request, recover it into
/// ExecutionError::NotFinished.
///
fn rpcerror_recover_cancelled<T>(
  operation_name: String,
  err: tower_grpc::Error<T>,
) -> Result<bazel_protos::google::longrunning::Operation, tower_grpc::Error<T>> {
  // If the error represented cancellation, return an Operation for the given Operation name.
  match &err {
    &tower_grpc::Error::Grpc(ref status) if status.code() == tower_grpc::Code::Cancelled => {
      return Ok(bazel_protos::google::longrunning::Operation {
        name: operation_name,
        done: false,
        metadata: None,
        result: None,
      });
    }
    _ => {}
  }
  // Did not represent cancellation.
  Err(err)
}

fn towergrpcerror_to_string<T: std::fmt::Debug>(error: tower_grpc::Error<T>) -> String {
  match error {
    tower_grpc::Error::Grpc(status) => {
      let error_message = if status.error_message() == "" {
        "[no message]"
      } else {
        &status.error_message()
      };
      format!("{:?}: {}", status.code(), error_message)
    }
    tower_grpc::Error::Inner(v) => format!("{:?}", v),
  }
}

fn timespec_from(timestamp: &Option<prost_types::Timestamp>) -> time::Timespec {
  if let Some(timestamp) = timestamp {
    time::Timespec::new(timestamp.seconds, timestamp.nanos)
  } else {
    time::Timespec::new(0, 0)
  }
}

#[cfg(test)]
mod tests {
  use bazel_protos;
  use bytes::{Bytes, BytesMut};
  use fs;
  use futures::Future;
  use hashing::{Digest, Fingerprint};
  use mock;
  use prost::Message;
  use prost_types;
  use protobuf::{self, ProtobufEnum};
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
  use std::sync::Arc;
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

    let want_execute_request = bazel_protos::build::bazel::remote::execution::v2::ExecuteRequest {
      action_digest: Some(
        (&Digest(
          Fingerprint::from_hex_string(
            "844c929423444f3392e0dcc89ebf1febbfdf3a2e2fcab7567cc474705a5385e4",
          )
          .unwrap(),
          140,
        ))
          .into(),
      ),
      ..Default::default()
    };

    assert_eq!(
      super::make_execute_request(&req, &None, &None),
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

    let want_execute_request = bazel_protos::build::bazel::remote::execution::v2::ExecuteRequest {
      action_digest: Some(
        (&Digest(
          Fingerprint::from_hex_string(
            "844c929423444f3392e0dcc89ebf1febbfdf3a2e2fcab7567cc474705a5385e4",
          )
          .unwrap(),
          140,
        ))
          .into(),
      ),
      instance_name: "dark-tower".to_owned(),
      ..Default::default()
    };

    assert_eq!(
      super::make_execute_request(&req, &Some("dark-tower".to_owned()), &None),
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

    let want_execute_request = bazel_protos::build::bazel::remote::execution::v2::ExecuteRequest {
      action_digest: Some(
        (&Digest(
          Fingerprint::from_hex_string(
            "0ee5d4c8ac12513a87c8d949c6883ac533a264d30215126af71a9028c4ab6edf",
          )
          .unwrap(),
          140,
        ))
          .into(),
      ),
      ..Default::default()
    };

    assert_eq!(
      super::make_execute_request(&req, &None, &Some("meep".to_owned())),
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

    let want_execute_request = bazel_protos::build::bazel::remote::execution::v2::ExecuteRequest {
      action_digest: Some(
        (&Digest(
          Fingerprint::from_hex_string(
            "b1fb7179ce496995a4e3636544ec000dca1b951f1f6216493f6c7608dc4dd910",
          )
          .unwrap(),
          140,
        ))
          .into(),
      ),
      ..Default::default()
    };

    assert_eq!(
      super::make_execute_request(&req, &None, &None),
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
        )
        .unwrap()
        .2,
        vec![],
      ))
    };

    let error = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");
    assert_eq!(
      error,
      "InvalidArgument: Did not expect this request".to_string()
    );
  }

  #[test]
  fn successful_execution_after_one_getoperation() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request, &None, &None)
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
    let test_stdout = TestData::roland();
    let test_stderr = TestData::catnip();

    let mock_server = {
      let op_name = "cat".to_owned();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&echo_roland_request(), &None, &None)
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
      Arc::new(fs::ResettablePool::new("test-pool-".to_owned())),
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

    let mut rt = tokio::runtime::Runtime::new().unwrap();

    let cmd_runner = CommandRunner::new(
      &mock_server.address(),
      None,
      None,
      None,
      store,
      timer_thread,
    )
    .unwrap();
    let result = rt.block_on(cmd_runner.run(echo_roland_request())).unwrap();
    rt.shutdown_now().wait().unwrap();
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

    let local_store = fs::Store::local_only(
      &store_dir_path,
      Arc::new(fs::ResettablePool::new("test-pool-".to_string())),
    )
    .expect("Error creating local store");
    {
      assert_eq!(
        local_store
          .load_file_bytes_with(test_stdout.digest(), |v| v)
          .wait()
          .unwrap(),
        Some(test_stdout.bytes())
      );
      assert_eq!(
        local_store
          .load_file_bytes_with(test_stderr.digest(), |v| v)
          .wait()
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
        super::make_execute_request(&execute_request, &None, &None)
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
        super::make_execute_request(&execute_request, &None, &None)
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
        super::make_execute_request(&execute_request, &None, &None)
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
        super::make_execute_request(&execute_request, &None, &None)
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          MockOperation::new({
            bazel_protos::google::longrunning::Operation {
              name: op_name.clone(),
              done: true,
              result: Some(
                bazel_protos::google::longrunning::operation::Result::Response(prost_types::Any {
                  type_url: "build.bazel.remote.execution.v2.ExecuteResponse".to_string(),
                  value: vec![0x00, 0x00, 0x00],
                }),
              ),
              ..Default::default()
            }
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
        super::make_execute_request(&execute_request, &None, &None)
          .unwrap()
          .2,
        vec![MockOperation::new(
          bazel_protos::google::longrunning::Operation {
            name: op_name.clone(),
            done: true,
            result: Some(bazel_protos::google::longrunning::operation::Result::Error(
              bazel_protos::google::rpc::Status {
                code: bazel_protos::code::Code::INTERNAL.value(),
                message: "Something went wrong".to_string(),
                details: vec![],
              },
            )),
            ..Default::default()
          },
        )],
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
        super::make_execute_request(&execute_request, &None, &None)
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          MockOperation::new(bazel_protos::google::longrunning::Operation {
            name: op_name.clone(),
            done: true,
            result: Some(bazel_protos::google::longrunning::operation::Result::Error(
              bazel_protos::google::rpc::Status {
                code: bazel_protos::code::Code::INTERNAL.value(),
                message: "Something went wrong".to_string(),
                details: vec![],
              },
            )),
            ..Default::default()
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
        super::make_execute_request(&execute_request, &None, &None)
          .unwrap()
          .2,
        vec![MockOperation::new(
          bazel_protos::google::longrunning::Operation {
            name: op_name.clone(),
            done: true,
            result: None,
            ..Default::default()
          },
        )],
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
        super::make_execute_request(&execute_request, &None, &None)
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          MockOperation::new(bazel_protos::google::longrunning::Operation {
            name: op_name.clone(),
            done: true,
            result: None,
            ..Default::default()
          }),
        ],
      ))
    };

    let result = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");

    assert_eq!(result, "Operation finished but no response supplied");
  }

  #[test]
  fn execute_missing_file_uploads_if_known() {
    let roland = TestData::roland();

    let mock_server = {
      let op_name = "cat".to_owned();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&cat_roland_request(), &None, &None)
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
      Arc::new(fs::ResettablePool::new("test-pool-".to_owned())),
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
    store
      .record_directory(&TestDirectory::containing_roland().directory(), false)
      .wait()
      .expect("Saving directory bytes to store");

    let mut rt = tokio::runtime::Runtime::new().unwrap();

    let result = rt.block_on(
      CommandRunner::new(
        &mock_server.address(),
        None,
        None,
        None,
        store,
        timer_thread,
      )
      .unwrap()
      .run(cat_roland_request()),
    );
    rt.shutdown_now().wait().unwrap();
    assert_eq!(
      result.unwrap().without_execution_attempts(),
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

      let status = make_precondition_failure_status(vec![missing_preconditionfailure_violation(
        &roland.digest(),
      )]);

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&cat_roland_request(), &None, &None)
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
      Arc::new(fs::ResettablePool::new("test-pool-".to_owned())),
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

    let mut rt = tokio::runtime::Runtime::new().unwrap();
    let result = rt.block_on(
      CommandRunner::new(
        &mock_server.address(),
        None,
        None,
        None,
        store,
        timer_thread,
      )
      .unwrap()
      .run(cat_roland_request()),
    );
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
        super::make_execute_request(&cat_roland_request(), &None, &None)
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
      Arc::new(fs::ResettablePool::new("test-pool-".to_owned())),
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

    let mut rt = tokio::runtime::Runtime::new().unwrap();
    let result = rt.block_on(
      CommandRunner::new(
        &mock_server.address(),
        None,
        None,
        None,
        store,
        timer_thread,
      )
      .unwrap()
      .run(cat_roland_request()),
    );
    rt.shutdown_now().wait().unwrap();
    let error = result.expect_err("Want error");
    assert_contains(&error, &format!("{}", missing_digest.0));
  }

  #[test]
  fn format_error_complete() {
    let error = bazel_protos::google::rpc::Status {
      code: bazel_protos::code::Code::CANCELLED.value(),
      message: "Oops, oh well!".to_string(),
      details: vec![],
    };
    assert_eq!(
      super::format_error(&error),
      "CANCELLED: Oops, oh well!".to_string()
    );
  }

  #[test]
  fn extract_execute_response_unknown_code() {
    let error = bazel_protos::google::rpc::Status {
      code: 555,
      message: "Oops, oh well!".to_string(),
      details: vec![],
    };
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

    let response = bazel_protos::build::bazel::remote::execution::v2::ExecuteResponse {
      result: Some(
        bazel_protos::build::bazel::remote::execution::v2::ActionResult {
          exit_code: want_result.exit_code,
          stdout_raw: want_result.stdout.to_vec(),
          stderr_raw: want_result.stderr.to_vec(),
          output_files: vec![
            bazel_protos::build::bazel::remote::execution::v2::OutputFile {
              path: "cats/roland".to_string(),
              digest: Some((&TestData::roland().digest()).into()),
              is_executable: false,
            },
          ],
          ..Default::default()
        },
      ),
      ..Default::default()
    };

    let operation = bazel_protos::google::longrunning::Operation {
      name: "cat".to_owned(),
      done: true,
      result: Some(
        bazel_protos::google::longrunning::operation::Result::Response(
          make_any_prost_executeresponse(&response),
        ),
      ),
      ..Default::default()
    };

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
    let operation = bazel_protos::google::longrunning::Operation {
      name: operation_name.clone(),
      done: false,
      ..Default::default()
    };

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
      bazel_protos::google::rpc::precondition_failure::Violation {
        type_: "MISSING".to_string(),
        subject: "monkeys".to_string(),
        description: "".to_string(),
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
    let missing = vec![bazel_protos::google::rpc::precondition_failure::Violation {
      type_: "OUT_OF_CAPACITY".to_string(),
      ..Default::default()
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
    let operation = bazel_protos::google::longrunning::Operation {
      name: "cat".to_owned(),
      done: true,
      result: Some(
        bazel_protos::google::longrunning::operation::Result::Response(
          make_any_prost_executeresponse(
            &bazel_protos::build::bazel::remote::execution::v2::ExecuteResponse {
              status: Some(bazel_protos::google::rpc::Status {
                code: bazel_protos::google::rpc::Code::PermissionDenied.into(),
                ..Default::default()
              }),
              ..Default::default()
            },
          ),
        ),
      ),
      ..Default::default()
    };

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
          super::make_execute_request(&execute_request, &None, &None)
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
          super::make_execute_request(&execute_request, &None, &None)
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
    let result = bazel_protos::build::bazel::remote::execution::v2::ActionResult {
      exit_code: 0,
      output_files: vec![
        bazel_protos::build::bazel::remote::execution::v2::OutputFile {
          path: "roland".to_string(),
          digest: Some((&TestData::roland().digest()).into()),
          is_executable: false,
        },
      ],
      ..Default::default()
    };
    assert_eq!(
      extract_output_files_from_response(&result),
      Ok(TestDirectory::containing_roland().digest())
    )
  }

  #[test]
  fn extract_output_files_from_response_two_files_not_nested() {
    let output_files = vec![
      bazel_protos::build::bazel::remote::execution::v2::OutputFile {
        path: "roland".to_string(),
        digest: Some((&TestData::roland().digest()).into()),
        is_executable: false,
      },
      bazel_protos::build::bazel::remote::execution::v2::OutputFile {
        path: "treats".to_string(),
        digest: Some((&TestData::catnip().digest()).into()),
        is_executable: false,
      },
    ];

    let result = bazel_protos::build::bazel::remote::execution::v2::ActionResult {
      output_files,
      ..Default::default()
    };

    assert_eq!(
      extract_output_files_from_response(&result),
      Ok(TestDirectory::containing_roland_and_treats().digest())
    )
  }

  #[test]
  fn extract_output_files_from_response_two_files_nested() {
    let output_files = vec![
      bazel_protos::build::bazel::remote::execution::v2::OutputFile {
        path: "cats/roland".to_string(),
        digest: Some((&TestData::roland().digest()).into()),
        is_executable: false,
      },
      bazel_protos::build::bazel::remote::execution::v2::OutputFile {
        path: "treats".to_string(),
        digest: Some((&TestData::catnip().digest()).into()),
        is_executable: false,
      },
    ];

    let result = bazel_protos::build::bazel::remote::execution::v2::ActionResult {
      output_files,
      ..Default::default()
    };

    assert_eq!(
      extract_output_files_from_response(&result),
      Ok(TestDirectory::recursive().digest())
    )
  }

  #[test]
  fn extract_output_files_from_response_just_directory() {
    let result = bazel_protos::build::bazel::remote::execution::v2::ActionResult {
      exit_code: 0,
      output_directories: vec![
        bazel_protos::build::bazel::remote::execution::v2::OutputDirectory {
          path: "cats".to_owned(),
          tree_digest: Some((&TestDirectory::containing_roland().digest()).into()),
        },
      ],
      ..Default::default()
    };

    assert_eq!(
      extract_output_files_from_response(&result),
      Ok(TestDirectory::nested().digest())
    )
  }

  #[test]
  fn extract_output_files_from_response_directories_and_files() {
    // /catnip
    // /pets/cats/roland
    // /pets/dogs/robin

    let result = bazel_protos::build::bazel::remote::execution::v2::ActionResult {
      output_files: vec![
        bazel_protos::build::bazel::remote::execution::v2::OutputFile {
          path: "treats".to_owned(),
          digest: Some((&TestData::catnip().digest()).into()),
          is_executable: false,
        },
      ],
      output_directories: vec![
        bazel_protos::build::bazel::remote::execution::v2::OutputDirectory {
          path: "pets/cats".to_owned(),
          tree_digest: Some((&TestDirectory::containing_roland().digest()).into()),
        },
        bazel_protos::build::bazel::remote::execution::v2::OutputDirectory {
          path: "pets/dogs".to_owned(),
          tree_digest: Some((&TestDirectory::containing_robin().digest()).into()),
        },
      ],
      ..Default::default()
    };

    assert_eq!(
      extract_output_files_from_response(&result),
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
    MockOperation::new(bazel_protos::google::longrunning::Operation {
      name: operation_name.to_string(),
      done: false,
      ..Default::default()
    })
  }

  fn make_delayed_incomplete_operation(operation_name: &str, delay: Duration) -> MockOperation {
    let op = bazel_protos::google::longrunning::Operation {
      name: operation_name.to_string(),
      done: false,
      ..Default::default()
    };
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
    let (stdout_raw, stdout_digest) = match stdout {
      StdoutType::Raw(stdout_raw) => (stdout_raw.as_bytes().to_vec(), None),
      StdoutType::Digest(stdout_digest) => (vec![], Some((&stdout_digest).into())),
    };

    let (stderr_raw, stderr_digest) = match stderr {
      StderrType::Raw(stderr_raw) => (stderr_raw.as_bytes().to_vec(), None),
      StderrType::Digest(stderr_digest) => (vec![], Some((&stderr_digest).into())),
    };

    let response_proto = bazel_protos::build::bazel::remote::execution::v2::ExecuteResponse {
      result: Some(
        bazel_protos::build::bazel::remote::execution::v2::ActionResult {
          stdout_raw,
          stdout_digest,
          stderr_raw,
          stderr_digest,
          exit_code,
          ..Default::default()
        },
      ),
      ..Default::default()
    };

    let op = bazel_protos::google::longrunning::Operation {
      name: operation_name.to_string(),
      done: true,
      result: Some(
        bazel_protos::google::longrunning::operation::Result::Response(
          make_any_prost_executeresponse(&response_proto),
        ),
      ),
      ..Default::default()
    };
    MockOperation::new(op)
  }

  fn make_precondition_failure_operation(
    violations: Vec<bazel_protos::google::rpc::precondition_failure::Violation>,
  ) -> MockOperation {
    let response = bazel_protos::build::bazel::remote::execution::v2::ExecuteResponse {
      status: Some(make_precondition_failure_status(violations)),
      ..Default::default()
    };
    let operation = bazel_protos::google::longrunning::Operation {
      name: "cat".to_string(),
      done: true,
      result: Some(
        bazel_protos::google::longrunning::operation::Result::Response(
          make_any_prost_executeresponse(&response),
        ),
      ),
      ..Default::default()
    };
    MockOperation::new(operation)
  }

  fn make_precondition_failure_status(
    violations: Vec<bazel_protos::google::rpc::precondition_failure::Violation>,
  ) -> bazel_protos::google::rpc::Status {
    bazel_protos::google::rpc::Status {
      code: bazel_protos::google::rpc::Code::FailedPrecondition.into(),
      details: vec![make_any_prost_proto(
        "google.rpc.PreconditionFailure",
        &bazel_protos::google::rpc::PreconditionFailure { violations },
      )],
      ..Default::default()
    }
  }

  fn run_command_remote(
    address: String,
    request: ExecuteProcessRequest,
  ) -> Result<FallibleExecuteProcessResult, String> {
    let cas = mock::StubCAS::builder()
      .file(&TestData::roland())
      .directory(&TestDirectory::containing_roland())
      .build();
    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    let command_runner = create_command_runner(address, &cas);
    let result = runtime.block_on(command_runner.run(request));
    runtime.shutdown_now().wait().unwrap();
    result
  }

  fn create_command_runner(address: String, cas: &mock::StubCAS) -> CommandRunner {
    let store_dir = TempDir::new().unwrap();
    let timer_thread = timer_thread();
    let store = fs::Store::with_remote(
      store_dir,
      Arc::new(fs::ResettablePool::new("test-pool-".to_owned())),
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

    CommandRunner::new(&address, None, None, None, store, timer_thread)
      .expect("Failed to make command runner")
  }

  fn timer_thread() -> resettable::Resettable<futures_timer::HelperThread> {
    resettable::Resettable::new(|| futures_timer::HelperThread::new().unwrap())
  }

  fn extract_execute_response(
    operation: bazel_protos::google::longrunning::Operation,
  ) -> Result<FallibleExecuteProcessResult, ExecutionError> {
    let cas = mock::StubCAS::builder()
      .file(&TestData::roland())
      .directory(&TestDirectory::containing_roland())
      .build();
    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    let command_runner = create_command_runner("127.0.0.1:0".to_owned(), &cas);
    let result = runtime.block_on(command_runner.extract_execute_response(
      super::OperationOrStatus::Operation(operation),
      &mut ExecutionHistory::default(),
    ));

    runtime.shutdown_now().wait().unwrap();
    result
  }

  fn extract_output_files_from_response(
    result: &bazel_protos::build::bazel::remote::execution::v2::ActionResult,
  ) -> Result<Digest, ExecutionError> {
    let cas = mock::StubCAS::builder()
      .file(&TestData::roland())
      .directory(&TestDirectory::containing_roland())
      .build();

    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    let command_runner = create_command_runner("127.0.0.1:0".to_owned(), &cas);
    let result = runtime.block_on(command_runner.extract_output_files(result));
    runtime.shutdown_now().wait().unwrap();
    result
  }

  fn make_any_prost_executeresponse(
    message: &bazel_protos::build::bazel::remote::execution::v2::ExecuteResponse,
  ) -> prost_types::Any {
    make_any_prost_proto("build.bazel.remote.execution.v2.ExecuteResponse", message)
  }

  fn make_any_prost_proto<M: Message>(message_name: &str, message: &M) -> prost_types::Any {
    let size = message.encoded_len();
    let mut value = BytesMut::with_capacity(size);
    message.encode(&mut value).expect("Error serializing proto");
    prost_types::Any {
      type_url: format!("type.googleapis.com/{}", message_name),
      value: value.to_vec(),
    }
  }

  fn missing_preconditionfailure_violation(
    digest: &Digest,
  ) -> bazel_protos::google::rpc::precondition_failure::Violation {
    {
      bazel_protos::google::rpc::precondition_failure::Violation {
        type_: "MISSING".to_owned(),
        subject: format!("blobs/{}/{}", digest.0, digest.1),
        ..Default::default()
      }
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
