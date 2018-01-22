use std::error::Error;
use std::sync::Arc;

use bazel_protos;
use boxfuture::{BoxFuture, Boxable};
use digest::{Digest, FixedOutput};
use futures::{Future, future};
use grpcio;
use protobuf::{self, Message, ProtobufEnum};
use sha2::Sha256;

use super::{ExecuteProcessRequest, ExecuteProcessResult};

pub struct CommandRunner {
  execution_client: Arc<bazel_protos::remote_execution_grpc::ExecutionClient>,
  operations_client: Arc<bazel_protos::operations_grpc::OperationsClient>,
}

#[derive(Debug, Eq, PartialEq)]
enum ExecutionError {
  Fatal(String),
  NotFinished(String),
}

impl CommandRunner {
  pub fn new(address: &str, thread_count: usize) -> CommandRunner {
    let env = Arc::new(grpcio::Environment::new(thread_count));
    let channel = grpcio::ChannelBuilder::new(env.clone()).connect(address);
    let execution_client = Arc::new(bazel_protos::remote_execution_grpc::ExecutionClient::new(
      channel.clone(),
    ));
    let operations_client = Arc::new(bazel_protos::operations_grpc::OperationsClient::new(
      channel.clone(),
    ));

    CommandRunner {
      execution_client,
      operations_client,
    }
  }

  ///
  /// Runs a command via a gRPC service implementing the Bazel Remote Execution API
  /// (https://docs.google.com/document/d/1AaGk7fOPByEvpAbqeXIyE8HX_A3_axxNnvroblTZ_6s/edit).
  ///
  /// Loops until the server gives a response, either successful or error. Does not have any
  /// timeout: polls in a tight loop.
  ///
  pub fn run_command_remote(
    &self,
    req: ExecuteProcessRequest,
  ) -> BoxFuture<ExecuteProcessResult, String> {
    let execution_client = self.execution_client.clone();
    let operations_client = self.operations_client.clone();
    future::done(make_execute_request(&req))
        .and_then(move |execute_request| {
          map_grpc_result(execution_client.execute(&execute_request))
        })
        // TODO: Use some better looping-frequency strategy than a tight-loop.
        // TODO: Add a timeout of some kind.
        .and_then(move |operation| future::loop_fn(operation, move |operation| {
          match extract_execute_response(operation) {
            Ok(value) => return Ok(future::Loop::Break(value)),
            Err(ExecutionError::Fatal(err)) => Err(err),
            Err(ExecutionError::NotFinished(operation_name)) => {
              let mut operation_request = bazel_protos::operations::GetOperationRequest::new();
              operation_request.set_name(operation_name);
              Ok(
                future::Loop::Continue(
                  map_grpc_result(operations_client.get_operation(&operation_request))?
                )
              )
            },
          }
        })).to_boxed()
  }
}

fn make_execute_request(
  req: &ExecuteProcessRequest,
) -> Result<bazel_protos::remote_execution::ExecuteRequest, String> {
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

  let mut execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  execute_request.set_action(action);

  Ok(execute_request)
}

fn extract_execute_response(
  mut operation: bazel_protos::operations::Operation,
) -> Result<ExecuteProcessResult, ExecutionError> {
  if !operation.get_done() {
    return Err(ExecutionError::NotFinished(operation.take_name()));
  }
  if operation.has_error() {
    return Err(ExecutionError::Fatal(format_error(&operation.get_error())));
  }
  if !operation.has_response() {
    return Err(ExecutionError::Fatal(
      "Operation finished but no response supplied".to_owned(),
    ));
  }
  let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
  execute_response
    .merge_from_bytes(operation.get_response().get_value())
    .map_err(|e| {
      ExecutionError::Fatal(format!("Error deserializing operation response: {:?}", e))
    })?;

  Ok(ExecuteProcessResult {
    stdout: execute_response.get_result().get_stdout_raw().to_vec(),
    stderr: execute_response.get_result().get_stderr_raw().to_vec(),
    exit_code: execute_response.get_result().get_exit_code(),
  })
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
  use protobuf::{self, Message, ProtobufEnum};
  use mock;
  use testutil::{owned_string_vec, as_byte_owned_vec};

  use super::{CommandRunner, ExecuteProcessRequest, ExecuteProcessResult};
  use std::collections::BTreeMap;
  use std::iter::{self, FromIterator};

  #[test]
  fn server_rejecting_execute_request_gives_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          "wrong-command".to_string(),
          super::make_execute_request(&ExecuteProcessRequest {
            argv: owned_string_vec(&["/bin/echo", "-n", "bar"]),
            env: BTreeMap::new(),
            input_files: fs::EMPTY_DIGEST,
          }).unwrap(),
          vec![],
        ).unwrap(),
      )
    };

    let error = run_command_remote(&mock_server.address(), execute_request).expect_err("Want Err");
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

      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request).unwrap(),
          vec![
            make_incomplete_operation(&op_name),
            make_successful_operation(&op_name, "foo", "", 0),
          ],
        ).unwrap(),
      )
    };

    let result = run_command_remote(&mock_server.address(), execute_request).unwrap();

    assert_eq!(
      result,
      ExecuteProcessResult {
        stdout: as_byte_owned_vec("foo"),
        stderr: as_byte_owned_vec(""),
        exit_code: 0,
      }
    );
  }

  #[test]
  fn successful_execution_after_ten_getoperations() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request).unwrap(),
          Vec::from_iter(
            iter::repeat(make_incomplete_operation(&op_name))
              .take(10)
              .chain(iter::once(
                make_successful_operation(&op_name, "foo", "", 0),
              )),
          ),
        ).unwrap(),
      )
    };

    let result = run_command_remote(&mock_server.address(), execute_request).unwrap();

    assert_eq!(
      result,
      ExecuteProcessResult {
        stdout: as_byte_owned_vec("foo"),
        stderr: as_byte_owned_vec(""),
        exit_code: 0,
      }
    );
  }

  #[test]
  fn bad_result_bytes() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request).unwrap(),
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
        ).unwrap(),
      )
    };

    run_command_remote(&mock_server.address(), execute_request).expect_err("Want Err");
  }

  #[test]
  fn initial_response_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request).unwrap(),
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
        ).unwrap(),
      )
    };

    let result = run_command_remote(&mock_server.address(), execute_request).expect_err("Want Err");

    assert_eq!(result, "INTERNAL: Something went wrong");
  }

  #[test]
  fn getoperation_response_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request).unwrap(),
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
        ).unwrap(),
      )
    };

    let result = run_command_remote(&mock_server.address(), execute_request).expect_err("Want Err");

    assert_eq!(result, "INTERNAL: Something went wrong");
  }

  #[test]
  fn initial_response_missing_response_and_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request).unwrap(),
          vec![
            {
              let mut op = bazel_protos::operations::Operation::new();
              op.set_name(op_name.to_string());
              op.set_done(true);
              op
            },
          ],
        ).unwrap(),
      )
    };

    let result = run_command_remote(&mock_server.address(), execute_request).expect_err("Want Err");

    assert_eq!(result, "Operation finished but no response supplied");
  }

  #[test]
  fn getoperation_missing_response_and_error() {
    let execute_request = echo_foo_request();

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request).unwrap(),
          vec![
            make_incomplete_operation(&op_name),
            {
              let mut op = bazel_protos::operations::Operation::new();
              op.set_name(op_name.to_string());
              op.set_done(true);
              op
            },
          ],
        ).unwrap(),
      )
    };

    let result = run_command_remote(&mock_server.address(), execute_request).expect_err("Want Err");

    assert_eq!(result, "Operation finished but no response supplied");
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
  fn digest() {
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
    stdout: &str,
    stderr: &str,
    exit_code: i32,
  ) -> bazel_protos::operations::Operation {
    let mut op = bazel_protos::operations::Operation::new();
    op.set_name(operation_name.to_string());
    op.set_done(true);
    op.set_response({
      let mut response_proto = bazel_protos::remote_execution::ExecuteResponse::new();
      response_proto.set_result({
        let mut action_result = bazel_protos::remote_execution::ActionResult::new();
        action_result.set_stdout_raw(Bytes::from(stdout));
        action_result.set_stderr_raw(Bytes::from(stderr));
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

  fn run_command_remote(
    address: &str,
    request: ExecuteProcessRequest,
  ) -> Result<ExecuteProcessResult, String> {
    CommandRunner::new(address, 1)
      .run_command_remote(request)
      .wait()
  }
}
