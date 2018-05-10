use std::error::Error;
use std::sync::Arc;

use bazel_protos;
use boxfuture::{BoxFuture, Boxable};
use bytes::Bytes;
use digest::{Digest as DigestTrait, FixedOutput};
use fs::Store;
use futures::{future, Future};
use futures_timer::Delay;
use grpcio;
use hashing::{Digest, Fingerprint};
use protobuf::{self, Message, ProtobufEnum};
use resettable::Resettable;
use sha2::Sha256;

use super::{ExecuteProcessRequest, ExecuteProcessResult};
use std::cmp::min;
use std::time::Duration;

#[derive(Clone)]
pub struct CommandRunner {
  channel: Resettable<grpcio::Channel>,
  env: Resettable<Arc<grpcio::Environment>>,
  execution_client: Resettable<Arc<bazel_protos::remote_execution_grpc::ExecutionClient>>,
  operations_client: Resettable<Arc<bazel_protos::operations_grpc::OperationsClient>>,
  store: Store,
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

macro_rules! try_future {
  ($x:expr) => {{
    match $x {
      Ok(value) => value,
      Err(error) => {
        return future::err(error).to_boxed();
      }
    }
  }};
}

impl CommandRunner {
  const BACKOFF_INCR_WAIT_MILLIS: u64 = 500;
  const BACKOFF_MAX_WAIT_MILLIS: u64 = 5000;

  pub fn new(address: String, thread_count: usize, store: Store) -> CommandRunner {
    let env = Resettable::new(Arc::new(move || {
      Arc::new(grpcio::Environment::new(thread_count))
    }));
    let env2 = env.clone();
    let channel = Resettable::new(Arc::new(move || {
      grpcio::ChannelBuilder::new(env2.get()).connect(&address)
    }));
    let channel2 = channel.clone();
    let channel3 = channel.clone();
    let execution_client = Resettable::new(Arc::new(move || {
      Arc::new(bazel_protos::remote_execution_grpc::ExecutionClient::new(
        channel2.get(),
      ))
    }));
    let operations_client = Resettable::new(Arc::new(move || {
      Arc::new(bazel_protos::operations_grpc::OperationsClient::new(
        channel3.get(),
      ))
    }));

    CommandRunner {
      channel,
      env,
      execution_client,
      operations_client,
      store,
    }
  }

  pub fn reset_prefork(&self) {
    self.channel.reset();
    self.env.reset();
    self.execution_client.reset();
    self.operations_client.reset();
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
  pub fn run_command_remote(
    &self,
    req: ExecuteProcessRequest,
  ) -> BoxFuture<ExecuteProcessResult, String> {
    let execution_client = self.execution_client.clone();
    let execution_client2 = execution_client.clone();
    let operations_client = self.operations_client.clone();

    let store = self.store.clone();
    let execute_request_result = make_execute_request(&req);

    match execute_request_result {
      Ok((command, execute_request)) => {
        let command_runner = self.clone();
        self.upload_command(&command, execute_request.get_action().get_command_digest().into())
          .and_then(move |_| {
            debug!("Executing remotely request: {:?} (command: {:?})", execute_request, command);

            map_grpc_result(execution_client.get().execute(&execute_request))
                .map(|result| (Arc::new(execute_request), result))
          })

          // TODO: Add a timeout of some kind.
          // https://github.com/pantsbuild/pants/issues/5504

          .and_then(move |(execute_request, operation)| {
            future::loop_fn((operation, 0), move |(operation, iter_num)| {

              let execute_request = execute_request.clone();
              let execution_client2 = execution_client2.clone();
              let store = store.clone();
              let operations_client = operations_client.clone();
              command_runner.extract_execute_response(operation)
                  .map(|value|  future::Loop::Break(value))
                  .or_else(move |value| {
                    match value {
                      ExecutionError::Fatal(err) => {
                        future::err(err).to_boxed()
                      },
                      ExecutionError::MissingDigests(missing_digests) => {
                        debug!(
                        "Server reported missing digests; trying to upload: {:?}",
                        missing_digests
                        );
                        let execute_request = execute_request.clone();
                        let execution_client2 = execution_client2.clone();
                        store.ensure_remote_has_recursive(missing_digests)
                            .and_then(move |()| {
                              map_grpc_result(
                                execution_client2.get().execute(
                                  &execute_request.clone()
                                )
                              )
                            })
                            // Reset `iter_num` on `MissingDigests`
                            .map(|operation| future::Loop::Continue((operation, 0)))
                            .to_boxed()
                      },
                      ExecutionError::NotFinished(operation_name) => {
                        let mut operation_request =
                          bazel_protos::operations::GetOperationRequest::new();
                        operation_request.set_name(operation_name.clone());

                        let backoff_period = min(
                      CommandRunner::BACKOFF_MAX_WAIT_MILLIS,
                      (1 + iter_num) * CommandRunner::BACKOFF_INCR_WAIT_MILLIS);

                        let grpc_result = map_grpc_result(
                    operations_client.get().get_operation(&operation_request));

                        Delay::new(Duration::from_millis(backoff_period))
                          .map_err(move |e| format!(
                            "Future-Delay errored at operation result polling for {}: {}",
                              operation_name, e))
                            .and_then(move |_| {
                              future::ok(
                             future::Loop::Continue(
                                  (try_future!(grpc_result), iter_num + 1))).to_boxed()
                            }).to_boxed()
                      },
                    }
                  })
              })
            }).to_boxed()
      }
      Err(err) => future::err(err).to_boxed(),
    }
  }

  fn upload_command(
    &self,
    command: &bazel_protos::remote_execution::Command,
    command_digest: Digest,
  ) -> BoxFuture<(), String> {
    let store = self.store.clone();
    let store2 = store.clone();
    future::done(
      command
        .write_to_bytes()
        .map_err(|e| format!("Error serializing command {:?}", e)),
    ).and_then(move |command_bytes| store.store_file_bytes(Bytes::from(command_bytes), true))
      .map_err(|e| format!("Error saving digest to local store: {:?}", e))
      .and_then(move |_| {
        // TODO: Tune when we upload the command.
        store2
          .ensure_remote_has_recursive(vec![command_digest])
          .map_err(|e| format!("Error uploading command {:?}", e))
          .map(|_| ())
      })
      .to_boxed()
  }

  fn extract_execute_response(
    &self,
    mut operation: bazel_protos::operations::Operation,
  ) -> BoxFuture<ExecuteProcessResult, ExecutionError> {
    // TODO: Log less verbosely
    debug!("Got operation response: {:?}", operation);
    if !operation.get_done() {
      return future::err(ExecutionError::NotFinished(operation.take_name())).to_boxed();
    }
    if operation.has_error() {
      return future::err(ExecutionError::Fatal(format_error(&operation.get_error()))).to_boxed();
    }
    if !operation.has_response() {
      return future::err(ExecutionError::Fatal(
        "Operation finished but no response supplied".to_string(),
      )).to_boxed();
    }
    let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
    try_future!(
      execute_response
        .merge_from_bytes(operation.get_response().get_value())
        .map_err(|e| ExecutionError::Fatal(format!("Invalid ExecuteResponse: {:?}", e)))
    );
    // TODO: Log less verbosely
    debug!("Got (nested) execute response: {:?}", execute_response);

    self
      .extract_stdout(&execute_response)
      .join(self.extract_stderr(&execute_response))
      .and_then(move |(stdout, stderr)| {
        match grpcio::RpcStatusCode::from(execute_response.get_status().get_code()) {
          grpcio::RpcStatusCode::Ok => future::ok(ExecuteProcessResult {
            stdout: stdout,
            stderr: stderr,
            exit_code: execute_response.get_result().get_exit_code(),
          }).to_boxed(),
          grpcio::RpcStatusCode::FailedPrecondition => {
            if execute_response.get_status().get_details().len() != 1 {
              return future::err(ExecutionError::Fatal(format!(
              "Received multiple details in FailedPrecondition ExecuteResponse's status field: {:?}",
              execute_response.get_status().get_details()
            ))).to_boxed();
            }
            let details = execute_response.get_status().get_details().get(0).unwrap();
            let mut precondition_failure = bazel_protos::error_details::PreconditionFailure::new();
            if details.get_type_url()
              != format!(
                "type.googleapis.com/{}",
                precondition_failure.descriptor().full_name()
              ) {
              return future::err(ExecutionError::Fatal(format!(
                "Received FailedPrecondition, but didn't know how to resolve it: {},\
                 protobuf type {}",
                execute_response.get_status().get_message(),
                details.get_type_url()
              ))).to_boxed();
            }
            try_future!(
              precondition_failure
                .merge_from_bytes(details.get_value())
                .map_err(|e| {
                  ExecutionError::Fatal(format!(
                    "Error deserializing FailedPrecondition proto: {:?}",
                    e
                  ))
                })
            );

            let mut missing_digests =
              Vec::with_capacity(precondition_failure.get_violations().len());

            for violation in precondition_failure.get_violations() {
              if violation.get_field_type() != "MISSING" {
                return future::err(ExecutionError::Fatal(format!(
                  "Didn't know how to process PreconditionFailure violation: {:?}",
                  violation
                ))).to_boxed();
              }
              let parts: Vec<_> = violation.get_subject().split("/").collect();
              if parts.len() != 3 || parts.get(0).unwrap() != &"blobs" {
                return future::err(ExecutionError::Fatal(format!(
                  "Received FailedPrecondition MISSING but didn't recognize subject {}",
                  violation.get_subject()
                ))).to_boxed();
              }
              let digest = Digest(
                try_future!(
                  Fingerprint::from_hex_string(parts.get(1).unwrap()).map_err(|e| {
                    ExecutionError::Fatal(format!(
                      "Bad digest in missing blob: {}: {}",
                      parts.get(1).unwrap(),
                      e
                    ))
                  })
                ),
                try_future!(parts.get(2).unwrap().parse::<usize>().map_err(|e| {
                  ExecutionError::Fatal(format!(
                    "Missing blob had bad size: {}: {}",
                    parts.get(2).unwrap(),
                    e
                  ))
                })),
              );
              missing_digests.push(digest);
            }
            if missing_digests.len() == 0 {
              return future::err(ExecutionError::Fatal(
                "Error from remote execution: FailedPrecondition, but no details".to_owned(),
              )).to_boxed();
            }
            return future::err(ExecutionError::MissingDigests(missing_digests)).to_boxed();
          }
          code => future::err(ExecutionError::Fatal(format!(
            "Error from remote execution: {:?}: {:?}",
            code,
            execute_response.get_status().get_message()
          ))).to_boxed(),
        }
      })
      .to_boxed()
  }

  fn extract_stdout(
    &self,
    execute_response: &bazel_protos::remote_execution::ExecuteResponse,
  ) -> BoxFuture<Bytes, ExecutionError> {
    let stdout = if execute_response.get_result().has_stdout_digest() {
      let stdout_digest = execute_response.get_result().get_stdout_digest().into();
      self
        .store
        .load_file_bytes_with(stdout_digest, |v| v)
        .map_err(move |error| {
          ExecutionError::Fatal(format!(
            "Error fetching stdout digest ({:?}): {:?}",
            stdout_digest, error
          ))
        })
        .and_then(move |maybe_value| match maybe_value {
          Some(value) => return Ok(value),
          None => {
            return Err(ExecutionError::Fatal(format!(
              "Couldn't find stdout digest ({:?}), when fetching.",
              stdout_digest
            )))
          }
        })
        .to_boxed()
    } else {
      future::ok(Bytes::from(execute_response.get_result().get_stdout_raw())).to_boxed()
    };
    return stdout;
  }

  fn extract_stderr(
    &self,
    execute_response: &bazel_protos::remote_execution::ExecuteResponse,
  ) -> BoxFuture<Bytes, ExecutionError> {
    let stderr = if execute_response.get_result().has_stderr_digest() {
      let stderr_digest = execute_response.get_result().get_stderr_digest().into();
      self
        .store
        .load_file_bytes_with(stderr_digest, |v| v)
        .map_err(move |error| {
          ExecutionError::Fatal(format!(
            "Error fetching stderr digest ({:?}): {:?}",
            stderr_digest, error
          ))
        })
        .and_then(move |maybe_value| match maybe_value {
          Some(value) => return Ok(value),
          None => {
            return Err(ExecutionError::Fatal(format!(
              "Couldn't find stderr digest ({:?}), when fetching.",
              stderr_digest
            )))
          }
        })
        .to_boxed()
    } else {
      future::ok(Bytes::from(execute_response.get_result().get_stderr_raw())).to_boxed()
    };
    return stderr;
  }
}

fn make_execute_request(
  req: &ExecuteProcessRequest,
) -> Result<
  (
    bazel_protos::remote_execution::Command,
    bazel_protos::remote_execution::ExecuteRequest,
  ),
  String,
> {
  let mut command = bazel_protos::remote_execution::Command::new();
  command.set_arguments(protobuf::RepeatedField::from_vec(req.argv.clone()));
  for (ref name, ref value) in req.env.iter() {
    let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
    env.set_name(name.to_string());
    env.set_value(value.to_string());
    command.mut_environment_variables().push(env);
  }

  let mut action = bazel_protos::remote_execution::Action::new();
  action.set_command_digest(digest(&command)?);
  action.set_input_root_digest((&req.input_files).into());

  let mut execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  execute_request.set_action(action);

  Ok((command, execute_request))
}

fn format_error(error: &bazel_protos::status::Status) -> String {
  let error_code_enum = bazel_protos::code::Code::from_i32(error.get_code());
  let error_code = match error_code_enum {
    Some(x) => format!("{:?}", x),
    None => format!("{:?}", error.get_code()),
  };
  format!("{}: {}", error_code, error.get_message())
}

fn map_grpc_result<T>(result: grpcio::Result<T>) -> Result<T, String> {
  match result {
    Ok(value) => Ok(value),
    Err(grpcio::Error::RpcFailure(status)) => Err(format!(
      "{:?}: {:?}",
      status.status,
      status.details.unwrap_or("[no message]".to_string())
    )),
    Err(err) => Err(err.description().to_string()),
  }
}

fn digest(message: &protobuf::Message) -> Result<bazel_protos::remote_execution::Digest, String> {
  let bytes = match message.write_to_bytes() {
    Ok(b) => b,
    Err(e) => return Err(e.description().to_string()),
  };

  let mut hasher = Sha256::default();
  hasher.input(&bytes);

  let mut digest = bazel_protos::remote_execution::Digest::new();
  digest.set_size_bytes(bytes.len() as i64);
  digest.set_hash(format!("{:x}", hasher.fixed_result()));

  return Ok(digest);
}

#[cfg(test)]
mod tests {
  use bazel_protos;
  use bytes::Bytes;
  use fs;
  use futures::Future;
  use grpcio;
  use hashing::Digest;
  use mock;
  use protobuf::{self, Message, ProtobufEnum};
  use tempdir::TempDir;
  use testutil::data::{TestData, TestDirectory};
  use testutil::{as_bytes, owned_string_vec};

  use super::{CommandRunner, ExecuteProcessRequest, ExecuteProcessResult, ExecutionError};
  use std::collections::BTreeMap;
  use std::iter::{self, FromIterator};
  use std::sync::Arc;
  use std::time::Duration;
  use std::time::SystemTime;

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
  fn server_rejecting_execute_request_gives_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        "wrong-command".to_string(),
        super::make_execute_request(&ExecuteProcessRequest {
          argv: owned_string_vec(&["/bin/echo", "-n", "bar"]),
          env: BTreeMap::new(),
          input_files: fs::EMPTY_DIGEST,
        }).unwrap()
          .1,
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
        super::make_execute_request(&execute_request).unwrap().1,
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
      result,
      ExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes(""),
        exit_code: 0,
      }
    );
  }

  #[test]
  fn extract_response_with_digest_stdout() {
    let op_name = "gimme-foo".to_string();
    let testdata = TestData::roland();
    let testdata_empty = TestData::empty();
    assert_eq!(
      extract_execute_response(make_successful_operation(
        &op_name,
        StdoutType::Digest(testdata.digest()),
        StderrType::Raw(testdata_empty.string()),
        0,
      )),
      Ok(ExecuteProcessResult {
        stdout: testdata.bytes(),
        stderr: testdata_empty.bytes(),
        exit_code: 0,
      })
    );
  }

  #[test]
  fn extract_response_with_digest_stderr() {
    let op_name = "gimme-foo".to_string();
    let testdata = TestData::roland();
    let testdata_empty = TestData::empty();
    assert_eq!(
      extract_execute_response(make_successful_operation(
        &op_name,
        StdoutType::Raw(testdata_empty.string()),
        StderrType::Digest(testdata.digest()),
        0,
      )),
      Ok(ExecuteProcessResult {
        stdout: testdata_empty.bytes(),
        stderr: testdata.bytes(),
        exit_code: 0,
      })
    );
  }

  #[test]
  fn successful_execution_after_four_getoperations() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&execute_request).unwrap().1,
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
      result,
      ExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes(""),
        exit_code: 0,
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
        super::make_execute_request(&execute_request).unwrap().1,
        vec![
          make_incomplete_operation(&op_name),
          {
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
          },
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
        super::make_execute_request(&execute_request).unwrap().1,
        vec![
          {
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
          },
        ],
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
        super::make_execute_request(&execute_request).unwrap().1,
        vec![
          make_incomplete_operation(&op_name),
          {
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
          },
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
        super::make_execute_request(&execute_request).unwrap().1,
        vec![
          {
            let mut op = bazel_protos::operations::Operation::new();
            op.set_name(op_name.to_string());
            op.set_done(true);
            op
          },
        ],
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
        super::make_execute_request(&execute_request).unwrap().1,
        vec![
          make_incomplete_operation(&op_name),
          {
            let mut op = bazel_protos::operations::Operation::new();
            op.set_name(op_name.to_string());
            op.set_done(true);
            op
          },
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
        super::make_execute_request(&cat_roland_request())
          .unwrap()
          .1,
        vec![
          make_incomplete_operation(&op_name),
          make_precondition_failure_operation(vec![
            missing_preconditionfailure_violation(&roland.digest()),
          ]),
          make_successful_operation(
            "cat2",
            StdoutType::Raw(roland.string()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        ],
      ))
    };

    let store_dir = TempDir::new("store").unwrap();
    let cas = mock::StubCAS::with_content(1024, vec![], vec![TestDirectory::containing_roland()]);
    let store = fs::Store::with_remote(
      store_dir,
      Arc::new(fs::ResettablePool::new("test-pool-".to_owned())),
      cas.address(),
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
    ).expect("Failed to make store");
    store
      .store_file_bytes(roland.bytes(), false)
      .wait()
      .expect("Saving file bytes to store");

    let result = CommandRunner::new(mock_server.address(), 1, store)
      .run_command_remote(cat_roland_request())
      .wait();
    assert_eq!(
      result,
      Ok(ExecuteProcessResult {
        stdout: roland.bytes(),
        stderr: Bytes::from(""),
        exit_code: 0,
      })
    );
    {
      let blobs = cas.blobs.lock().unwrap();
      assert_eq!(blobs.get(&roland.fingerprint()), Some(&roland.bytes()));
    }
  }

  #[test]
  fn execute_missing_file_errors_if_unknown() {
    let missing_digest = TestData::roland().digest();

    let mock_server = {
      let op_name = "cat".to_owned();

      mock::execution_server::TestServer::new(mock::execution_server::MockExecution::new(
        op_name.clone(),
        super::make_execute_request(&cat_roland_request())
          .unwrap()
          .1,
        vec![
          make_incomplete_operation(&op_name),
          make_precondition_failure_operation(vec![
            missing_preconditionfailure_violation(&missing_digest),
          ]),
        ],
      ))
    };

    let store_dir = TempDir::new("store").unwrap();
    let cas = mock::StubCAS::with_content(1024, vec![], vec![TestDirectory::containing_roland()]);
    let store = fs::Store::with_remote(
      store_dir,
      Arc::new(fs::ResettablePool::new("test-pool-".to_owned())),
      cas.address(),
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
    ).expect("Failed to make store");

    let error = CommandRunner::new(mock_server.address(), 1, store)
      .run_command_remote(cat_roland_request())
      .wait()
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
    let want_result = ExecuteProcessResult {
      stdout: as_bytes("roland"),
      stderr: Bytes::from("simba"),
      exit_code: 17,
    };

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
        result
      });
      response
    }));

    assert_eq!(extract_execute_response(operation), Ok(want_result));
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

    let operation = make_precondition_failure_operation(missing);

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

    let operation = make_precondition_failure_operation(missing);

    match extract_execute_response(operation) {
      Err(ExecutionError::Fatal(err)) => assert_contains(&err, "monkeys"),
      other => assert!(false, "Want fatal error, got {:?}", other),
    };
  }

  #[test]
  fn extract_execute_response_other_failed_precondition() {
    let missing = vec![
      {
        let mut violation = bazel_protos::error_details::PreconditionFailure_Violation::new();
        violation.set_field_type("OUT_OF_CAPACITY".to_owned());
        violation
      },
    ];

    let operation = make_precondition_failure_operation(missing);

    match extract_execute_response(operation) {
      Err(ExecutionError::Fatal(err)) => assert_contains(&err, "OUT_OF_CAPACITY"),
      other => assert!(false, "Want fatal error, got {:?}", other),
    };
  }

  #[test]
  fn extract_execute_response_missing_without_list() {
    let missing = vec![];

    let operation = make_precondition_failure_operation(missing);

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
      digest.get_hash(),
      "a32cd427e5df6a998199266681692989f56c19cabd1cc637bdd56ae2e62619b4"
    );
    assert_eq!(digest.get_size_bytes(), 32)
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
          super::make_execute_request(&execute_request).unwrap().1,
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
      let start_time = SystemTime::now();
      run_command_remote(mock_server.address(), execute_request).unwrap();
      assert!(start_time.elapsed().unwrap() >= Duration::from_millis(500));
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
          super::make_execute_request(&execute_request).unwrap().1,
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
      let start_time = SystemTime::now();
      run_command_remote(mock_server.address(), execute_request).unwrap();
      assert!(start_time.elapsed().unwrap() >= Duration::from_millis(3000));
    }
  }

  fn echo_foo_request() -> ExecuteProcessRequest {
    ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
    }
  }

  fn make_incomplete_operation(operation_name: &str) -> bazel_protos::operations::Operation {
    let mut op = bazel_protos::operations::Operation::new();
    op.set_name(operation_name.to_string());
    op.set_done(false);
    op
  }

  fn make_successful_operation(
    operation_name: &str,
    stdout: StdoutType,
    stderr: StderrType,
    exit_code: i32,
  ) -> bazel_protos::operations::Operation {
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
    op
  }

  fn make_precondition_failure_operation(
    violations: Vec<bazel_protos::error_details::PreconditionFailure_Violation>,
  ) -> bazel_protos::operations::Operation {
    let mut operation = bazel_protos::operations::Operation::new();
    operation.set_name("cat".to_owned());
    operation.set_done(true);
    operation.set_response(make_any_proto(&{
      let mut response = bazel_protos::remote_execution::ExecuteResponse::new();
      response.set_status({
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
      });
      response
    }));
    operation
  }

  fn run_command_remote(
    address: String,
    request: ExecuteProcessRequest,
  ) -> Result<ExecuteProcessResult, String> {
    let cas = mock::StubCAS::with_roland_and_directory(1024);
    let command_runner = create_command_runner(address, &cas);
    command_runner.run_command_remote(request).wait()
  }

  fn create_command_runner(address: String, cas: &mock::StubCAS) -> CommandRunner {
    let store_dir = TempDir::new("store").unwrap();
    let store = fs::Store::with_remote(
      store_dir,
      Arc::new(fs::ResettablePool::new("test-pool-".to_owned())),
      cas.address(),
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
    ).expect("Failed to make store");

    CommandRunner::new(address, 1, store)
  }

  fn extract_execute_response(
    operation: bazel_protos::operations::Operation,
  ) -> Result<ExecuteProcessResult, ExecutionError> {
    let cas = mock::StubCAS::with_roland_and_directory(1024);
    let command_runner = create_command_runner("".to_owned(), &cas);
    command_runner.extract_execute_response(operation).wait()
  }

  fn make_any_proto(message: &protobuf::Message) -> protobuf::well_known_types::Any {
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
    }
  }
}
