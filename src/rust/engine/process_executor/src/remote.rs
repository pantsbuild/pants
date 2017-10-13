use std::error::Error;
use std::sync::Arc;

use bazel_protos;
use digest::{Digest, FixedOutput};
use grpcio;
use protobuf::{self, Message};
use sha2::Sha256;

use super::{ExecuteProcessRequest, ExecuteProcessResult};

///
/// Runs a command via a gRPC service implementing the Bazel Remote Execution API
/// (https://docs.google.com/document/d/1AaGk7fOPByEvpAbqeXIyE8HX_A3_axxNnvroblTZ_6s/edit).
///
pub fn run_command_remote(
  addr: &str,
  req: ExecuteProcessRequest,
) -> Result<ExecuteProcessResult, String> {
  let execute_request = make_execute_request(&req)?;

  let env = Arc::new(grpcio::Environment::new(1));
  let channel = || grpcio::ChannelBuilder::new(env.clone()).connect(addr);
  let execution_client = bazel_protos::remote_execution_grpc::ExecutionClient::new(channel());

  let result = map_grpc_result(execution_client.execute(execute_request))?;

  // TODO: Check whether there's a response on this result.

  let operation_client = bazel_protos::operations_grpc::OperationsClient::new(channel());
  let mut operation_request = bazel_protos::operations::GetOperationRequest::new();
  operation_request.set_name(result.get_name().to_string());
  let operation_result = map_grpc_result(operation_client.get_operation(operation_request))?;

  let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();

  // TODO: Keep retrying until success.

  execute_response
    .merge_from_bytes(operation_result.get_response().get_value())
    .map_err(|e| e.description().to_string())?;

  Ok(ExecuteProcessResult {
    stdout: execute_response.get_result().get_stdout_raw().to_vec(),
    stderr: execute_response.get_result().get_stderr_raw().to_vec(),
    exit_code: execute_response.get_result().get_exit_code(),
  })
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
  use protobuf;
  use protobuf::Message;
  use test_server;
  use test_utils::{owned_string_vec, as_byte_owned_vec};

  use super::{ExecuteProcessRequest, ExecuteProcessResult, run_command_remote};
  use std::collections::BTreeMap;

  #[test]
  fn server_rejects_execute_request() {
    let execute_request = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
    };

    let mock_server = {
      test_server::TestServer::new(
        test_server::MockExecution::new(
          "wrong-command".to_string(),
          super::make_execute_request(&ExecuteProcessRequest {
            argv: owned_string_vec(&["/bin/echo", "-n", "bar"]),
            env: BTreeMap::new(),
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
    let execute_request = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
    };

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      test_server::TestServer::new(
        test_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request).unwrap(),
          vec![
            {
              let mut op = bazel_protos::operations::Operation::new();
              op.set_name(op_name.clone());
              op.set_done(false);
              op
            },
            {
              let mut response_proto = bazel_protos::remote_execution::ExecuteResponse::new();
              response_proto.set_result({
                let mut action_result = bazel_protos::remote_execution::ActionResult::new();
                action_result.set_stdout_raw("foo".as_bytes().to_vec());
                action_result.set_stderr_raw("".as_bytes().to_vec());
                action_result.set_exit_code(0);
                action_result
              });

              let mut response_wrapper = protobuf::well_known_types::Any::new();
              response_wrapper.set_type_url(format!(
                "type.googleapis.com/{}",
                response_proto.descriptor().full_name()
              ));
              let response_proto_bytes = response_proto.write_to_bytes().unwrap();
              response_wrapper.set_value(response_proto_bytes);

              let mut op = bazel_protos::operations::Operation::new();
              op.set_name(op_name.clone());
              op.set_done(true);
              op.set_response(response_wrapper);
              op
            },
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
    )
  }

  #[test]
  fn bad_result_bytes() {
    let execute_request = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
    };

    let mock_server = {
      let op_name = "gimme-foo".to_string();

      test_server::TestServer::new(
        test_server::MockExecution::new(
          op_name.clone(),
          super::make_execute_request(&execute_request).unwrap(),
          vec![
            {
              let mut op = bazel_protos::operations::Operation::new();
              op.set_name(op_name.clone());
              op.set_done(false);
              op
            },
            {
              let mut response_wrapper = protobuf::well_known_types::Any::new();
              response_wrapper.set_type_url(format!(
                "type.googleapis.com/{}",
                bazel_protos::remote_execution::ExecuteResponse::new()
                  .descriptor()
                  .full_name()
              ));
              response_wrapper.set_value(vec![0x00, 0x00, 0x00]);

              let mut op = bazel_protos::operations::Operation::new();
              op.set_name(op_name.clone());
              op.set_done(true);
              op.set_response(response_wrapper);
              op
            },
          ],
        ).unwrap(),
      )
    };

    run_command_remote(&mock_server.address(), execute_request).expect_err("Want Err");
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
}
