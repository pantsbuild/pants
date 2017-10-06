use std::error::Error;

use bazel_protos;
use digest::{Digest, FixedOutput};
use protobuf;
use sha2::Sha256;

use super::{ExecuteProcessRequest, ExecuteProcessResult};

///
/// Runs a command via a gRPC service implementing the Bazel Remote Execution API
/// (https://docs.google.com/document/d/1AaGk7fOPByEvpAbqeXIyE8HX_A3_axxNnvroblTZ_6s/edit).
///
pub fn run_command_remote(req: ExecuteProcessRequest) -> Result<ExecuteProcessResult, String> {
  let mut command = bazel_protos::remote_execution::Command::new();
  command.set_arguments(protobuf::RepeatedField::from_vec(req.argv));
  for (name, value) in req.env {
    let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
    env.set_name(name);
    env.set_value(value);
    command.mut_environment_variables().push(env);
  }

  let mut action = bazel_protos::remote_execution::Action::new();
  action.set_command_digest(digest(&command)?);

  let mut execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  execute_request.set_action(action);

  unimplemented!();
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
