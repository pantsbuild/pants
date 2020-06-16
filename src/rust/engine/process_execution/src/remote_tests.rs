use bazel_protos;
use bazel_protos::operations::Operation;
use bazel_protos::remote_execution::ExecutedActionMetadata;
use bytes::Bytes;
use futures::compat::Future01CompatExt;
use grpcio;
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use mock;
use protobuf::{self, Message, ProtobufEnum};
use spectral::{assert_that, string::StrAssertions};
use std::convert::TryInto;
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use testutil::owned_string_vec;

use crate::remote::{CommandRunner, ExecutionError, ExecutionHistory, OperationOrStatus};
use crate::{
  CommandRunner as CommandRunnerTrait, Context, FallibleProcessResultWithPlatform,
  MultiPlatformProcess, Platform, PlatformConstraint, Process, ProcessMetadata,
};
use maplit::{btreemap, hashset};
use mock::execution_server::{ExpectedAPICall, MockOperation};
use protobuf::well_known_types::Timestamp;
use spectral::prelude::*;
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::ops::Sub;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tokio::runtime::Handle;
use tokio::time::{delay_for, timeout};
use workunit_store::{Workunit, WorkunitMetadata, WorkunitState, WorkunitStore};

#[derive(Debug, PartialEq)]
pub(crate) struct RemoteTestResult {
  pub(crate) original: FallibleProcessResultWithPlatform,
  pub(crate) stdout_bytes: Vec<u8>,
  pub(crate) stderr_bytes: Vec<u8>,
}

impl RemoteTestResult {
  pub fn stdout(&self) -> &str {
    std::str::from_utf8(&self.stdout_bytes).unwrap()
  }

  #[allow(dead_code)]
  pub fn stderr(&self) -> &str {
    std::str::from_utf8(&self.stderr_bytes).unwrap()
  }
}

#[derive(Debug, PartialEq)]
pub(crate) enum StdoutType {
  Raw(String),
  Digest(Digest),
}

#[derive(Debug, PartialEq)]
pub(crate) enum StderrType {
  Raw(String),
  Digest(Digest),
}

#[tokio::test]
async fn make_execute_request() {
  let input_directory = TestDirectory::containing_roland();
  let req = Process {
    argv: owned_string_vec(&["/bin/echo", "yo"]),
    env: vec![("SOME".to_owned(), "value".to_owned())]
      .into_iter()
      .collect(),
    working_directory: None,
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
    timeout: None,
    description: "some description".to_owned(),
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
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
  want_command.mut_platform().mut_properties().push({
    let mut property = bazel_protos::remote_execution::Platform_Property::new();
    property.set_name("target_platform".to_owned());
    property.set_value("none".to_owned());
    property
  });

  let mut want_action = bazel_protos::remote_execution::Action::new();
  want_action.set_command_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "6cfe2081e40c7542a8b369b669618fe7c6e690e274183e406ed75dc3959dc82f",
      )
      .unwrap(),
      99,
    ))
      .into(),
  );
  want_action.set_input_root_digest((&input_directory.digest()).into());

  let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  want_execute_request.set_action_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "1b52d1997da65c69c5fe2f8717caa6e538dabc13f90f16332454d95b1f8949a4",
      )
      .unwrap(),
      140,
    ))
      .into(),
  );

  assert_eq!(
    crate::remote::make_execute_request(&req, empty_request_metadata()),
    Ok((want_action, want_command, want_execute_request))
  );
}

#[tokio::test]
async fn make_execute_request_with_instance_name() {
  let input_directory = TestDirectory::containing_roland();
  let req = Process {
    argv: owned_string_vec(&["/bin/echo", "yo"]),
    env: vec![("SOME".to_owned(), "value".to_owned())]
      .into_iter()
      .collect(),
    working_directory: None,
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
    timeout: None,
    description: "some description".to_owned(),
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
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
  want_command.mut_platform().mut_properties().push({
    let mut property = bazel_protos::remote_execution::Platform_Property::new();
    property.set_name("target_platform".to_owned());
    property.set_value("apple-2e".to_owned()); // overridden by metadata, see below
    property
  });

  let mut want_action = bazel_protos::remote_execution::Action::new();
  want_action.set_command_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "12111c5c43433f428dfd53ba1f44dfdcad1ae88ecf4560930eeb8eec54551c99",
      )
      .unwrap(),
      103,
    ))
      .into(),
  );
  want_action.set_input_root_digest((&input_directory.digest()).into());

  let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  want_execute_request.set_instance_name("dark-tower".to_owned());
  want_execute_request.set_action_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "f850dad74061fb0919212274da8137d647dde16ec1623c13f0f8eafa4d83a823",
      )
      .unwrap(),
      140,
    ))
      .into(),
  );

  assert_eq!(
    crate::remote::make_execute_request(
      &req,
      ProcessMetadata {
        instance_name: Some("dark-tower".to_owned()),
        cache_key_gen_version: None,
        platform_properties: vec![("target_platform".to_owned(), "apple-2e".to_owned())],
      }
    ),
    Ok((want_action, want_command, want_execute_request))
  );
}

#[tokio::test]
async fn make_execute_request_with_cache_key_gen_version() {
  let input_directory = TestDirectory::containing_roland();
  let req = Process {
    argv: owned_string_vec(&["/bin/echo", "yo"]),
    env: vec![("SOME".to_owned(), "value".to_owned())]
      .into_iter()
      .collect(),
    working_directory: None,
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
    timeout: None,
    description: "some description".to_owned(),
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
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
    env.set_name(crate::remote::CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_owned());
    env.set_value("meep".to_owned());
    env
  });
  want_command
    .mut_environment_variables()
    .sort_by(|x, y| x.name.cmp(&y.name));
  want_command
    .mut_output_files()
    .push("other/file".to_owned());
  want_command
    .mut_output_files()
    .push("path/to/file".to_owned());
  want_command
    .mut_output_directories()
    .push("directory/name".to_owned());
  want_command.mut_platform().mut_properties().push({
    let mut property = bazel_protos::remote_execution::Platform_Property::new();
    property.set_name("target_platform".to_owned());
    property.set_value("none".to_owned());
    property
  });

  let mut want_action = bazel_protos::remote_execution::Action::new();
  want_action.set_command_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "0b560be42712036a85ae33f1570eb12918c0763515517fb9511008dd5615e9d7",
      )
      .unwrap(),
      136,
    ))
      .into(),
  );
  want_action.set_input_root_digest((&input_directory.digest()).into());

  let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  want_execute_request.set_action_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "c07f61ace0d3aa8182f4f9248b15dc7ee0a873b5d1f74ac50b70e0c8cbda0122",
      )
      .unwrap(),
      141,
    ))
      .into(),
  );

  assert_eq!(
    crate::remote::make_execute_request(
      &req,
      ProcessMetadata {
        instance_name: None,
        cache_key_gen_version: Some("meep".to_owned()),
        platform_properties: vec![],
      }
    ),
    Ok((want_action, want_command, want_execute_request))
  );
}

#[tokio::test]
async fn make_execute_request_with_jdk() {
  let input_directory = TestDirectory::containing_roland();
  let req = Process {
    argv: owned_string_vec(&["/bin/echo", "yo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: input_directory.digest(),
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: None,
    description: "some description".to_owned(),
    append_only_caches: BTreeMap::new(),
    jdk_home: Some(PathBuf::from("/tmp")),
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
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
  want_command.mut_platform().mut_properties().push({
    let mut property = bazel_protos::remote_execution::Platform_Property::new();
    property.set_name("target_platform".to_owned());
    property.set_value("none".to_owned());
    property
  });

  let mut want_action = bazel_protos::remote_execution::Action::new();
  want_action.set_command_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "9a396c5e4359a0e6289c4112098e2851d608fe730e2584881b7182ef08229a42",
      )
      .unwrap(),
      63,
    ))
      .into(),
  );
  want_action.set_input_root_digest((&input_directory.digest()).into());

  let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  want_execute_request.set_action_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "de42e6b80e82818bda020ac5a3b6f040a9d7cef6e4a5aecb5001b6a098a2fe28",
      )
      .unwrap(),
      140,
    ))
      .into(),
  );

  assert_eq!(
    crate::remote::make_execute_request(&req, empty_request_metadata()),
    Ok((want_action, want_command, want_execute_request))
  );
}

#[tokio::test]
async fn make_execute_request_with_jdk_and_extra_platform_properties() {
  let input_directory = TestDirectory::containing_roland();
  let req = Process {
    argv: owned_string_vec(&["/bin/echo", "yo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: input_directory.digest(),
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: None,
    description: "some description".to_owned(),
    append_only_caches: BTreeMap::new(),
    jdk_home: Some(PathBuf::from("/tmp")),
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
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
    property.set_name("Multi".to_owned());
    property.set_value("dos".to_owned());
    property
  });
  want_command.mut_platform().mut_properties().push({
    let mut property = bazel_protos::remote_execution::Platform_Property::new();
    property.set_name("Multi".to_owned());
    property.set_value("uno".to_owned());
    property
  });
  want_command.mut_platform().mut_properties().push({
    let mut property = bazel_protos::remote_execution::Platform_Property::new();
    property.set_name("last".to_owned());
    property.set_value("bar".to_owned());
    property
  });
  want_command.mut_platform().mut_properties().push({
    let mut property = bazel_protos::remote_execution::Platform_Property::new();
    property.set_name("target_platform".to_owned());
    property.set_value("none".to_owned());
    property
  });

  let mut want_action = bazel_protos::remote_execution::Action::new();
  want_action.set_command_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "741a33b863aaa595e2be6a316f9ae187e3c0d8cf8a8054261417eebbede0cefe",
      )
      .unwrap(),
      118,
    ))
      .into(),
  );
  want_action.set_input_root_digest((&input_directory.digest()).into());

  let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  want_execute_request.set_action_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "c3dc9c1e73f5cdfbf7e3b55dd6dead4f6fe03323dc19db87b27617fede27e9b4",
      )
      .unwrap(),
      140,
    ))
      .into(),
  );

  assert_eq!(
    crate::remote::make_execute_request(
      &req,
      ProcessMetadata {
        instance_name: None,
        cache_key_gen_version: None,
        platform_properties: vec![
          ("FIRST".to_owned(), "foo".to_owned()),
          ("Multi".to_owned(), "uno".to_owned()),
          ("last".to_owned(), "bar".to_owned()),
          ("Multi".to_owned(), "dos".to_owned()),
        ]
      },
    ),
    Ok((want_action, want_command, want_execute_request))
  );
}

#[tokio::test]
async fn make_execute_request_with_timeout() {
  let input_directory = TestDirectory::containing_roland();
  let req = Process {
    argv: owned_string_vec(&["/bin/echo", "yo"]),
    env: vec![("SOME".to_owned(), "value".to_owned())]
      .into_iter()
      .collect(),
    working_directory: None,
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
    timeout: one_second(),
    description: "some description".to_owned(),
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
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
  want_command.mut_platform().mut_properties().push({
    let mut property = bazel_protos::remote_execution::Platform_Property::new();
    property.set_name("target_platform".to_owned());
    property.set_value("none".to_owned());
    property
  });

  let mut want_action = bazel_protos::remote_execution::Action::new();
  want_action.set_command_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "6cfe2081e40c7542a8b369b669618fe7c6e690e274183e406ed75dc3959dc82f",
      )
      .unwrap(),
      99,
    ))
      .into(),
  );
  want_action.set_input_root_digest((&input_directory.digest()).into());

  let mut timeout_duration = protobuf::well_known_types::Duration::new();
  timeout_duration.set_seconds(1);
  want_action.set_timeout(timeout_duration);

  let mut want_execute_request = bazel_protos::remote_execution::ExecuteRequest::new();
  want_execute_request.set_action_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "4638ebe2e21095d9ce559041eb4961d2483e0f27659c3a6d930f7722c4878939",
      )
      .unwrap(),
      144,
    ))
      .into(),
  );

  assert_eq!(
    crate::remote::make_execute_request(&req, empty_request_metadata()),
    Ok((want_action, want_command, want_execute_request))
  );
}

#[tokio::test]
async fn server_rejecting_execute_request_gives_error() {
  let execute_request = echo_foo_request();

  let mock_server = mock::execution_server::TestServer::new(
    mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
      execute_request: crate::remote::make_execute_request(
        &Process::new(owned_string_vec(&["/bin/echo", "-n", "bar"])),
        empty_request_metadata(),
      )
      .map(|x| x.2)
      .unwrap(),
      stream_responses: Err(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::INVALID_ARGUMENT,
        None,
      )),
    }]),
    None,
  );

  let error = run_command_remote2(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");
  assert_that(&error).contains("INVALID_ARGUMENT");
  assert_that(&error).contains("Did not expect this request");
}

#[tokio::test]
async fn successful_execution_after_one_getoperation() {
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote2(mock_server.address(), execute_request)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn retries_retriable_errors() {
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_retryable_operation_failure(),
        },
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote2(mock_server.address(), execute_request)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_eq!(result.original.platform, Platform::Linux);

  assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn gives_up_after_many_retriable_errors() {
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_retryable_operation_failure(),
        },
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_retryable_operation_failure(),
        },
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_retryable_operation_failure(),
        },
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_retryable_operation_failure(),
        },
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_retryable_operation_failure(),
        },
      ]),
      None,
    )
  };

  let err = run_command_remote2(mock_server.address(), execute_request)
    .await
    .unwrap_err();

  assert_that!(err).contains("Gave up");
  assert_that!(err).contains("appears to be lost");

  assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn sends_headers() {
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        },
      ]),
      None,
    )
  };
  let cas = mock::StubCAS::empty();
  let runtime = task_executor::Executor::new(Handle::current());
  let store_dir = TempDir::new().unwrap();
  let store = Store::with_remote(
    runtime.clone(),
    store_dir,
    vec![cas.address()],
    None,
    None,
    None,
    1,
    10 * 1024 * 1024,
    Duration::from_secs(1),
    store::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .expect("Failed to make store");

  let command_runner = CommandRunner::new(
    &mock_server.address(),
    empty_request_metadata(),
    None,
    Some(String::from("catnip-will-get-you-anywhere")),
    btreemap! {
      String::from("cat") => String::from("roland"),
    },
    store,
    Platform::Linux,
    runtime.clone(),
    Duration::from_secs(0),
    Duration::from_millis(0),
    Duration::from_secs(0),
  )
  .unwrap();
  let context = Context {
    workunit_store: WorkunitStore::default(),
    build_id: String::from("marmosets"),
  };
  command_runner
    .run(execute_request, context)
    .await
    .expect("Execution failed");

  let received_messages = mock_server.mock_responder.received_messages.lock();
  let message_headers: Vec<_> = received_messages
    .iter()
    .map(|received_message| received_message.headers.clone())
    .collect();
  assert_that!(message_headers).has_length(2);
  for headers in message_headers {
    {
      let want_key = String::from("google.devtools.remoteexecution.v1test.requestmetadata-bin");
      assert_that!(headers).contains_key(&want_key);
      let mut proto = bazel_protos::remote_execution::RequestMetadata::new();
      proto
        .merge_from_bytes(&headers[&want_key])
        .expect("Failed to parse metadata proto");
      assert_eq!(proto.get_tool_details().get_tool_name(), "pants");
      assert_eq!(proto.get_tool_invocation_id(), "marmosets");
    }
    {
      let want_key = String::from("cat");
      assert_that!(headers).contains_key(&want_key);
      assert_eq!(headers[&want_key], "roland".as_bytes());
    }
    {
      let want_key = String::from("authorization");
      assert_that!(headers).contains_key(&want_key);
      assert_eq!(
        headers[&want_key],
        "Bearer catnip-will-get-you-anywhere".as_bytes()
      );
    }
  }
}

#[tokio::test]
async fn extract_response_with_digest_stdout() {
  let op_name = "gimme-foo".to_string();
  let testdata = TestData::roland();
  let testdata_empty = TestData::empty();
  let result = extract_execute_response(
    make_successful_operation(
      &op_name,
      StdoutType::Digest(testdata.digest()),
      StderrType::Raw(testdata_empty.string()),
      0,
    )
    .op
    .unwrap()
    .unwrap(),
    false,
    Platform::Linux,
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, testdata.bytes());
  assert_eq!(result.stderr_bytes, testdata_empty.bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_eq!(result.original.platform, Platform::Linux);
}

#[tokio::test]
async fn extract_response_with_digest_stderr() {
  let op_name = "gimme-foo".to_string();
  let testdata = TestData::roland();
  let testdata_empty = TestData::empty();
  let result = extract_execute_response(
    make_successful_operation(
      &op_name,
      StdoutType::Raw(testdata_empty.string()),
      StderrType::Digest(testdata.digest()),
      0,
    )
    .op
    .unwrap()
    .unwrap(),
    false,
    Platform::Linux,
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, testdata_empty.bytes());
  assert_eq!(result.stderr_bytes, testdata.bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_eq!(result.original.platform, Platform::Linux);
}

#[tokio::test]
async fn extract_response_with_digest_stdout_osx_remote() {
  let op_name = "gimme-foo".to_string();
  let testdata = TestData::roland();
  let testdata_empty = TestData::empty();
  let result = extract_execute_response(
    make_successful_operation(
      &op_name,
      StdoutType::Digest(testdata.digest()),
      StderrType::Raw(testdata_empty.string()),
      0,
    )
    .op
    .unwrap()
    .unwrap(),
    false,
    Platform::Darwin,
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, testdata.bytes());
  assert_eq!(result.stderr_bytes, testdata_empty.bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_eq!(result.original.platform, Platform::Darwin);
}

#[tokio::test]
async fn ensure_inline_stdio_is_stored() {
  let runtime = task_executor::Executor::new(Handle::current());

  let test_stdout = TestData::roland();
  let test_stderr = TestData::catnip();

  let mock_server = {
    let op_name = "cat".to_owned();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &echo_roland_request().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_successful_operation(
            &op_name.clone(),
            StdoutType::Raw(test_stdout.string()),
            StderrType::Raw(test_stderr.string()),
            0,
          ),
        },
      ]),
      None,
    )
  };

  let store_dir = TempDir::new().unwrap();
  let store_dir_path = store_dir.path();

  let cas = mock::StubCAS::empty();
  let store = Store::with_remote(
    runtime.clone(),
    &store_dir_path,
    vec![cas.address()],
    None,
    None,
    None,
    1,
    10 * 1024 * 1024,
    Duration::from_secs(1),
    store::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .expect("Failed to make store");

  let cmd_runner = CommandRunner::new(
    &mock_server.address(),
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store.clone(),
    Platform::Linux,
    runtime.clone(),
    Duration::from_secs(0),
    Duration::from_millis(0),
    Duration::from_secs(0),
  )
  .unwrap();

  let result = run_cmd_runner(echo_roland_request(), cmd_runner, store)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, test_stdout.bytes());
  assert_eq!(result.stderr_bytes, test_stderr.bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.platform, Platform::Linux);

  let local_store =
    Store::local_only(runtime.clone(), &store_dir_path).expect("Error creating local store");
  {
    assert_eq!(
      local_store
        .load_file_bytes_with(test_stdout.digest(), |v| Bytes::from(v))
        .await
        .unwrap()
        .unwrap()
        .0,
      test_stdout.bytes()
    );
    assert_eq!(
      local_store
        .load_file_bytes_with(test_stderr.digest(), |v| Bytes::from(v))
        .await
        .unwrap()
        .unwrap()
        .0,
      test_stderr.bytes()
    );
  }
}

#[tokio::test]
async fn successful_execution_after_four_getoperations() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_incomplete_operation(&op_name),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_incomplete_operation(&op_name),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_incomplete_operation(&op_name),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_incomplete_operation(&op_name),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote2(mock_server.address(), execute_request)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_eq!(result.original.platform, Platform::Linux);
}

#[tokio::test]
async fn timeout_after_sufficiently_delayed_getoperations() {
  let request_timeout = Duration::new(1, 0);
  // The request should timeout after 2 seconds, with 1 second due to the queue_buffer_time and
  // 1 due to the request_timeout.
  let delayed_operation_time = Duration::new(2, 500);

  let execute_request = Process {
    argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Some(request_timeout),
    description: "echo-a-foo".to_string(),
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  };

  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request,
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_delayed_incomplete_operation(&op_name, delayed_operation_time),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote2(mock_server.address(), execute_request.into())
    .await
    .unwrap();
  assert_eq!(result.original.exit_code, -15);
  let error_msg = String::from_utf8(result.stdout_bytes.to_vec()).unwrap();
  assert_that(&error_msg).contains("Exceeded user timeout");
  assert_that(&error_msg).contains("echo-a-foo");
  assert_eq!(result.original.execution_attempts.len(), 1);
  let maybe_execution_duration = result.original.execution_attempts[0].remote_execution;
  assert!(maybe_execution_duration.is_some());
  assert_that(&maybe_execution_duration.unwrap()).is_greater_than_or_equal_to(request_timeout);

  assert_cancellation_requests(&mock_server, vec![op_name.to_owned()]);
}

#[ignore] // flaky: https://github.com/pantsbuild/pants/issues/8405
#[tokio::test]
async fn dropped_request_cancels() {
  let request_timeout = Duration::new(10, 0);
  let delayed_operation_time = Duration::new(5, 0);

  let execute_request = Process {
    argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Some(request_timeout),
    description: "echo-a-foo".to_string(),
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  };

  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request,
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_delayed_incomplete_operation(&op_name, delayed_operation_time),
        },
      ]),
      None,
    )
  };

  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let (command_runner, _store) = create_command_runner(
    mock_server.address(),
    &cas,
    Duration::from_millis(0),
    Duration::from_secs(0),
    Platform::Linux,
  );

  // Give the command only 100 ms to run (although it needs a lot more than that).
  let run_future = command_runner.run(execute_request.into(), Context::default());
  if let Ok(_) = timeout(Duration::from_millis(100), run_future).await {
    panic!("Should have timed out.");
  }

  // Wait a bit longer for the cancellation to have been sent to the server.
  // TODO: Would be better to be able to await a notification from the server that "something"
  // had happened.
  delay_for(Duration::from_secs(3)).await;

  assert_cancellation_requests(&mock_server, vec![op_name.to_owned()]);
}

#[ignore] // flaky: https://github.com/pantsbuild/pants/issues/7149
#[tokio::test]
async fn retry_for_cancelled_channel() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_canceled_operation(Some(Duration::from_millis(100))),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote2(mock_server.address(), execute_request)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_eq!(result.original.platform, Platform::Linux);
}

#[tokio::test]
async fn bad_result_bytes() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: MockOperation::new({
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
        },
      ]),
      None,
    )
  };

  run_command_remote2(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");
}

#[tokio::test]
async fn initial_response_error() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
        execute_request: crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        stream_responses: Ok(vec![MockOperation::new({
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
        })]),
      }]),
      None,
    )
  };

  let result = run_command_remote2(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");

  assert_eq!(result, "INTERNAL: Something went wrong");
}

#[tokio::test]
async fn getoperation_response_error() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: MockOperation::new({
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
        },
      ]),
      None,
    )
  };

  let result = run_command_remote2(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");

  assert_eq!(result, "INTERNAL: Something went wrong");

  assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn initial_response_missing_response_and_error() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
        execute_request: crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        stream_responses: Ok(vec![MockOperation::new({
          let mut op = bazel_protos::operations::Operation::new();
          op.set_name(op_name.to_string());
          op.set_done(true);
          op
        })]),
      }]),
      None,
    )
  };

  let result = run_command_remote2(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");

  assert_eq!(result, "Operation finished but no response supplied");
}

#[tokio::test]
async fn getoperation_missing_response_and_error() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: MockOperation::new({
            let mut op = bazel_protos::operations::Operation::new();
            op.set_name(op_name.to_string());
            op.set_done(true);
            op
          }),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote2(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");

  assert_eq!(result, "Operation finished but no response supplied");
}

#[tokio::test]
async fn execute_missing_file_uploads_if_known() {
  let runtime = task_executor::Executor::new(Handle::current());

  let roland = TestData::roland();

  let mock_server = {
    let op_name = "cat".to_owned();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &cat_roland_request().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_precondition_failure_operation(vec![
            missing_preconditionfailure_violation(&roland.digest()),
          ]),
        },
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &cat_roland_request().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_successful_operation(
            "cat2",
            StdoutType::Raw(roland.string()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        },
      ]),
      None,
    )
  };

  let store_dir = TempDir::new().unwrap();
  let cas = mock::StubCAS::builder()
    .directory(&TestDirectory::containing_roland())
    .build();
  let store = Store::with_remote(
    runtime.clone(),
    store_dir,
    vec![cas.address()],
    None,
    None,
    None,
    1,
    10 * 1024 * 1024,
    Duration::from_secs(1),
    store::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .expect("Failed to make store");
  store
    .store_file_bytes(roland.bytes(), false)
    .await
    .expect("Saving file bytes to store");
  store
    .record_directory(&TestDirectory::containing_roland().directory(), false)
    .await
    .expect("Saving directory bytes to store");
  let command_runner = CommandRunner::new(
    &mock_server.address(),
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store.clone(),
    Platform::Linux,
    runtime.clone(),
    Duration::from_secs(0),
    Duration::from_millis(0),
    Duration::from_secs(0),
  )
  .unwrap();

  let result = run_cmd_runner(cat_roland_request(), command_runner, store)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, roland.bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.platform, Platform::Linux);

  {
    let blobs = cas.blobs.lock();
    assert_eq!(blobs.get(&roland.fingerprint()), Some(&roland.bytes()));
  }
}

#[tokio::test]
// TODO: Unignore this test when the server can actually fail with status protos.
#[ignore] // https://github.com/pantsbuild/pants/issues/6597
async fn execute_missing_file_uploads_if_known_status() {
  let roland = TestData::roland();

  let mock_server = {
    let op_name = "cat".to_owned();

    let status = grpcio::RpcStatus {
      status: grpcio::RpcStatusCode::FAILED_PRECONDITION,
      details: None,
      status_proto_bytes: Some(
        make_precondition_failure_status(vec![missing_preconditionfailure_violation(
          &roland.digest(),
        )])
        .write_to_bytes()
        .unwrap(),
      ),
    };

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &cat_roland_request().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![
            //make_incomplete_operation(&op_name),
            MockOperation {
              op: Err(status),
              duration: None,
            },
          ]),
        },
        ExpectedAPICall::GetOperation {
          operation_name: op_name.clone(),
          operation: make_successful_operation(
            "cat2",
            StdoutType::Raw(roland.string()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        },
      ]),
      None,
    )
  };

  let store_dir = TempDir::new().unwrap();
  let cas = mock::StubCAS::builder()
    .directory(&TestDirectory::containing_roland())
    .build();
  let runtime = task_executor::Executor::new(Handle::current());
  let store = Store::with_remote(
    runtime.clone(),
    store_dir,
    vec![cas.address()],
    None,
    None,
    None,
    1,
    10 * 1024 * 1024,
    Duration::from_secs(1),
    store::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .expect("Failed to make store");
  store
    .store_file_bytes(roland.bytes(), false)
    .await
    .expect("Saving file bytes to store");

  let command_runner = CommandRunner::new(
    &mock_server.address(),
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store.clone(),
    Platform::Linux,
    runtime.clone(),
    Duration::from_secs(0),
    Duration::from_millis(0),
    Duration::from_secs(0),
  )
  .unwrap();

  let result = run_cmd_runner(cat_roland_request(), command_runner, store)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, roland.bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.platform, Platform::Linux);
  {
    let blobs = cas.blobs.lock();
    assert_eq!(blobs.get(&roland.fingerprint()), Some(&roland.bytes()));
  }

  assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn execute_missing_file_errors_if_unknown() {
  let missing_digest = TestDirectory::containing_roland().digest();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![]),
      None,
    )
  };

  let store_dir = TempDir::new().unwrap();
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let runtime = task_executor::Executor::new(Handle::current());
  let store = Store::with_remote(
    runtime.clone(),
    store_dir,
    vec![cas.address()],
    None,
    None,
    None,
    1,
    10 * 1024 * 1024,
    Duration::from_secs(1),
    store::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .expect("Failed to make store");

  let runner = CommandRunner::new(
    &mock_server.address(),
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store,
    Platform::Linux,
    runtime.clone(),
    Duration::from_secs(0),
    Duration::from_millis(0),
    Duration::from_secs(0),
  )
  .unwrap();

  let error = runner
    .run(cat_roland_request(), Context::default())
    .await
    .expect_err("Want error");
  assert_contains(&error, &format!("{}", missing_digest.0));
}

#[tokio::test]
async fn format_error_complete() {
  let mut error = bazel_protos::status::Status::new();
  error.set_code(bazel_protos::code::Code::CANCELLED.value());
  error.set_message("Oops, oh well!".to_string());
  assert_eq!(
    crate::remote::format_error(&error),
    "CANCELLED: Oops, oh well!".to_string()
  );
}

#[tokio::test]
async fn extract_execute_response_unknown_code() {
  let mut error = bazel_protos::status::Status::new();
  error.set_code(555);
  error.set_message("Oops, oh well!".to_string());
  assert_eq!(
    crate::remote::format_error(&error),
    "555: Oops, oh well!".to_string()
  );
}

#[tokio::test]
async fn extract_execute_response_success() {
  let wanted_exit_code = 17;
  let wanted_stdout = Bytes::from("roland".as_bytes());
  let wanted_stderr = Bytes::from("simba".as_bytes());

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
      result.set_exit_code(wanted_exit_code);
      result.set_stdout_raw(Bytes::from(wanted_stdout.clone()));
      result.set_stderr_raw(Bytes::from(wanted_stderr.clone()));
      result.set_output_files(output_files);
      result
    });
    response
  }));

  let result = extract_execute_response(operation, false, Platform::Linux)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, wanted_stdout);
  assert_eq!(result.stderr_bytes, wanted_stderr);
  assert_eq!(result.original.exit_code, wanted_exit_code);
  assert_eq!(
    result.original.output_directory,
    TestDirectory::nested().digest()
  );
  assert_eq!(result.original.platform, Platform::Linux);
}

#[tokio::test]
async fn extract_execute_response_pending() {
  let operation_name = "cat".to_owned();
  let mut operation = bazel_protos::operations::Operation::new();
  operation.set_name(operation_name.clone());
  operation.set_done(false);

  assert_eq!(
    extract_execute_response(operation, false, Platform::Linux).await,
    Err(ExecutionError::NotFinished(operation_name))
  );
}

#[tokio::test]
async fn extract_execute_response_missing_digests() {
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
    extract_execute_response(operation, false, Platform::Linux).await,
    Err(ExecutionError::MissingDigests(missing_files))
  );
}

#[tokio::test]
async fn extract_execute_response_missing_other_things() {
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

  match extract_execute_response(operation, false, Platform::Linux).await {
    Err(ExecutionError::Fatal(err)) => assert_contains(&err, "monkeys"),
    other => assert!(false, "Want fatal error, got {:?}", other),
  };
}

#[tokio::test]
async fn extract_execute_response_other_failed_precondition() {
  let missing = vec![{
    let mut violation = bazel_protos::error_details::PreconditionFailure_Violation::new();
    violation.set_field_type("OUT_OF_CAPACITY".to_owned());
    violation
  }];

  let operation = make_precondition_failure_operation(missing)
    .op
    .unwrap()
    .unwrap();

  match extract_execute_response(operation, false, Platform::Linux).await {
    Err(ExecutionError::Fatal(err)) => assert_contains(&err, "OUT_OF_CAPACITY"),
    other => assert!(false, "Want fatal error, got {:?}", other),
  };
}

#[tokio::test]
async fn extract_execute_response_missing_without_list() {
  let missing = vec![];

  let operation = make_precondition_failure_operation(missing)
    .op
    .unwrap()
    .unwrap();

  match extract_execute_response(operation, false, Platform::Linux).await {
    Err(ExecutionError::Fatal(err)) => assert_contains(&err.to_lowercase(), "precondition"),
    other => assert!(false, "Want fatal error, got {:?}", other),
  };
}

#[tokio::test]
async fn extract_execute_response_other_status() {
  let mut operation = bazel_protos::operations::Operation::new();
  operation.set_name("cat".to_owned());
  operation.set_done(true);
  operation.set_response(make_any_proto(&{
    let mut response = bazel_protos::remote_execution::ExecuteResponse::new();
    response.set_status({
      let mut status = bazel_protos::status::Status::new();
      status.set_code(grpcio::RpcStatusCode::PERMISSION_DENIED.into());
      status
    });
    response
  }));

  match extract_execute_response(operation, false, Platform::Linux).await {
    Err(ExecutionError::Fatal(err)) => assert_contains(&err, "PERMISSION_DENIED"),
    other => assert!(false, "Want fatal error, got {:?}", other),
  };
}

#[tokio::test]
async fn extract_execute_response_timeout() {
  let operation_name = "cat".to_owned();
  let mut operation = bazel_protos::operations::Operation::new();
  operation.set_name(operation_name.clone());
  operation.set_done(false);

  assert_eq!(
    // The response would be NotFinished, but we pass `timeout_has_elapsed: true`.
    extract_execute_response(operation, true, Platform::Linux).await,
    Err(ExecutionError::Timeout)
  );
}

#[tokio::test]
async fn digest_command() {
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

  let digest = crate::remote::digest(&command).unwrap();

  assert_eq!(
    &digest.0.to_hex(),
    "a32cd427e5df6a998199266681692989f56c19cabd1cc637bdd56ae2e62619b4"
  );
  assert_eq!(digest.1, 32)
}

#[tokio::test]
async fn wait_between_request_1_retry() {
  // wait at least 100 milli for one retry
  {
    let execute_request = echo_foo_request();
    let mock_server = {
      let op_name = "gimme-foo".to_string();
      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(vec![
          ExpectedAPICall::Execute {
            execute_request: crate::remote::make_execute_request(
              &execute_request.clone().try_into().unwrap(),
              empty_request_metadata(),
            )
            .unwrap()
            .2,
            stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
          },
          ExpectedAPICall::GetOperation {
            operation_name: op_name.clone(),
            operation: make_successful_operation(
              &op_name,
              StdoutType::Raw("foo".to_owned()),
              StderrType::Raw("".to_owned()),
              0,
            ),
          },
        ]),
        None,
      )
    };
    let cas = mock::StubCAS::empty();
    let (command_runner, _store) = create_command_runner(
      mock_server.address(),
      &cas,
      Duration::from_millis(100),
      Duration::from_secs(1),
      Platform::Linux,
    );
    command_runner
      .run(execute_request, Context::default())
      .await
      .unwrap();

    let messages = mock_server.mock_responder.received_messages.lock();
    assert!(messages.len() == 2);
    assert!(
      messages
        .get(1)
        .unwrap()
        .received_at
        .sub(messages.get(0).unwrap().received_at)
        >= Duration::from_millis(100)
    );
  }
}

#[tokio::test]
async fn wait_between_request_3_retry() {
  // wait at least 50 + 100 + 150 = 300 milli for 3 retries.
  {
    let execute_request = echo_foo_request();
    let mock_server = {
      let op_name = "gimme-foo".to_string();
      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(vec![
          ExpectedAPICall::Execute {
            execute_request: crate::remote::make_execute_request(
              &execute_request.clone().try_into().unwrap(),
              empty_request_metadata(),
            )
            .unwrap()
            .2,
            stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
          },
          ExpectedAPICall::GetOperation {
            operation_name: op_name.clone(),
            operation: make_incomplete_operation(&op_name),
          },
          ExpectedAPICall::GetOperation {
            operation_name: op_name.clone(),
            operation: make_incomplete_operation(&op_name),
          },
          ExpectedAPICall::GetOperation {
            operation_name: op_name.clone(),
            operation: make_successful_operation(
              &op_name,
              StdoutType::Raw("foo".to_owned()),
              StderrType::Raw("".to_owned()),
              0,
            ),
          },
        ]),
        None,
      )
    };
    let cas = mock::StubCAS::empty();
    let (command_runner, _store) = create_command_runner(
      mock_server.address(),
      &cas,
      Duration::from_millis(50),
      Duration::from_secs(5),
      Platform::Linux,
    );
    command_runner
      .run(execute_request, Context::default())
      .await
      .unwrap();

    let messages = mock_server.mock_responder.received_messages.lock();
    assert!(messages.len() == 4);
    assert!(
      messages
        .get(1)
        .unwrap()
        .received_at
        .sub(messages.get(0).unwrap().received_at)
        >= Duration::from_millis(50)
    );
    assert!(
      messages
        .get(2)
        .unwrap()
        .received_at
        .sub(messages.get(1).unwrap().received_at)
        >= Duration::from_millis(100)
    );
    assert!(
      messages
        .get(3)
        .unwrap()
        .received_at
        .sub(messages.get(2).unwrap().received_at)
        >= Duration::from_millis(150)
    );
  }
}

#[tokio::test]
async fn extract_output_files_from_response_one_file() {
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
    extract_output_files_from_response(&execute_response).await,
    Ok(TestDirectory::containing_roland().digest())
  )
}

#[tokio::test]
async fn extract_output_files_from_response_two_files_not_nested() {
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
    extract_output_files_from_response(&execute_response).await,
    Ok(TestDirectory::containing_roland_and_treats().digest())
  )
}

#[tokio::test]
async fn extract_output_files_from_response_two_files_nested() {
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
    extract_output_files_from_response(&execute_response).await,
    Ok(TestDirectory::recursive().digest())
  )
}

#[tokio::test]
async fn extract_output_files_from_response_just_directory() {
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
    extract_output_files_from_response(&execute_response).await,
    Ok(TestDirectory::nested().digest())
  )
}

#[tokio::test]
async fn extract_output_files_from_response_directories_and_files() {
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
    extract_output_files_from_response(&execute_response).await,
    Ok(Digest(
      Fingerprint::from_hex_string(
        "639b4b84bb58a9353d49df8122e7987baf038efe54ed035e67910846c865b1e2"
      )
      .unwrap(),
      159
    ))
  )
}

#[tokio::test]
async fn extract_output_files_from_response_no_prefix() {
  let mut output_directory = bazel_protos::remote_execution::OutputDirectory::new();
  output_directory.set_path(String::new());
  output_directory.set_tree_digest((&TestDirectory::containing_roland().digest()).into());

  let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
  execute_response.set_result({
    let mut result = bazel_protos::remote_execution::ActionResult::new();
    result.set_exit_code(0);
    result.mut_output_directories().push(output_directory);
    result
  });

  assert_eq!(
    extract_output_files_from_response(&execute_response).await,
    Ok(TestDirectory::containing_roland().digest())
  )
}

pub(crate) fn workunits_with_constant_span_id(
  workunit_store: &mut WorkunitStore,
) -> HashSet<Workunit> {
  workunit_store.with_latest_workunits(log::Level::Trace, |_, completed_workunits| {
    completed_workunits
      .iter()
      .map(|workunit| Workunit {
        span_id: String::from("ignore"),
        ..workunit.clone()
      })
      .collect()
  })
}

#[tokio::test]
async fn remote_workunits_are_stored() {
  let mut workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);
  let op_name = "gimme-foo".to_string();
  let testdata = TestData::roland();
  let testdata_empty = TestData::empty();
  let operation = make_successful_operation_with_metadata(
    &op_name,
    StdoutType::Digest(testdata.digest()),
    StderrType::Raw(testdata_empty.string()),
    0,
  );
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let (command_runner, _store) = create_command_runner(
    "".to_owned(),
    &cas,
    std::time::Duration::from_millis(0),
    std::time::Duration::from_secs(0),
    Platform::Linux,
  );

  futures01::future::lazy(move || {
    command_runner.extract_execute_response(
      OperationOrStatus::Operation(operation),
      false,
      &mut ExecutionHistory::default(),
    )
  })
  .compat()
  .await
  .unwrap();

  let got_workunits = workunits_with_constant_span_id(&mut workunit_store);

  use concrete_time::Duration;
  use concrete_time::TimeSpan;

  let want_workunits = hashset! {
    Workunit {
      name: String::from("remote execution action scheduling"),
      state: WorkunitState::Completed {
        time_span: TimeSpan {
          start: Duration::new(0, 0),
          duration: Duration::new(1, 0),
        }
      },
      span_id: String::from("ignore"),
      parent_id: None,
      metadata: WorkunitMetadata::new(),
    },
    Workunit {
      name: String::from("remote execution worker input fetching"),
      state: WorkunitState::Completed {
        time_span: TimeSpan {
          start: Duration::new(2, 0),
          duration: Duration::new(1, 0),
        }
      },
      span_id: String::from("ignore"),
      parent_id: None,
      metadata: WorkunitMetadata::new(),
    },
    Workunit {
      name: String::from("remote execution worker command executing"),
      state: WorkunitState::Completed {
        time_span: TimeSpan {
          start: Duration::new(4, 0),
          duration: Duration::new(1, 0),
        }
      },
      span_id: String::from("ignore"),
      parent_id: None,
      metadata: WorkunitMetadata::new(),
    },
    Workunit {
      name: String::from("remote execution worker output uploading"),
      state: WorkunitState::Completed {
        time_span: TimeSpan {
          start: Duration::new(6, 0),
          duration: Duration::new(1, 0),
        }
      },
      span_id: String::from("ignore"),
      parent_id: None,
      metadata: WorkunitMetadata::new(),
    }
  };

  assert!(got_workunits.is_superset(&want_workunits));
}

pub fn echo_foo_request() -> MultiPlatformProcess {
  let req = Process {
    argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Some(Duration::from_millis(5000)),
    description: "echo a foo".to_string(),
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  };
  req.into()
}

fn make_canceled_operation(duration: Option<Duration>) -> MockOperation {
  MockOperation {
    op: Ok(None),
    duration,
  }
}

pub(crate) fn make_incomplete_operation(operation_name: &str) -> MockOperation {
  let mut op = bazel_protos::operations::Operation::new();
  op.set_name(operation_name.to_string());
  op.set_done(false);
  MockOperation::new(op)
}

pub(crate) fn make_retryable_operation_failure() -> MockOperation {
  let mut status = bazel_protos::status::Status::new();
  status.set_code(grpcio::RpcStatusCode::ABORTED.into());
  status.set_message(String::from("the bot running the task appears to be lost"));

  let mut operation = bazel_protos::operations::Operation::new();
  operation.set_done(true);
  operation.set_response(make_any_proto(&{
    let mut response = bazel_protos::remote_execution::ExecuteResponse::new();
    response.set_status(status);
    response
  }));

  MockOperation {
    op: Ok(Some(operation)),
    duration: None,
  }
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

fn make_successful_operation_with_maybe_metadata(
  operation_name: &str,
  stdout: StdoutType,
  stderr: StderrType,
  exit_code: i32,
  metadata: Option<ExecutedActionMetadata>,
) -> Operation {
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
      if let Some(metadata) = metadata {
        action_result.set_execution_metadata(metadata);
      };
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

pub(crate) fn make_successful_operation(
  operation_name: &str,
  stdout: StdoutType,
  stderr: StderrType,
  exit_code: i32,
) -> MockOperation {
  let op =
    make_successful_operation_with_maybe_metadata(operation_name, stdout, stderr, exit_code, None);
  MockOperation::new(op)
}

pub(crate) fn make_successful_operation_with_metadata(
  operation_name: &str,
  stdout: StdoutType,
  stderr: StderrType,
  exit_code: i32,
) -> Operation {
  let mut metadata = ExecutedActionMetadata::new();
  metadata.set_queued_timestamp(timestamp_only_secs(0));
  metadata.set_worker_start_timestamp(timestamp_only_secs(1));
  metadata.set_input_fetch_start_timestamp(timestamp_only_secs(2));
  metadata.set_input_fetch_completed_timestamp(timestamp_only_secs(3));
  metadata.set_execution_start_timestamp(timestamp_only_secs(4));
  metadata.set_execution_completed_timestamp(timestamp_only_secs(5));
  metadata.set_output_upload_start_timestamp(timestamp_only_secs(6));
  metadata.set_output_upload_completed_timestamp(timestamp_only_secs(7));
  metadata.set_worker_completed_timestamp(timestamp_only_secs(8));

  make_successful_operation_with_maybe_metadata(
    operation_name,
    stdout,
    stderr,
    exit_code,
    Some(metadata),
  )
}

fn timestamp_only_secs(v: i64) -> Timestamp {
  let mut dummy_timestamp = Timestamp::new();
  dummy_timestamp.set_seconds(v);
  dummy_timestamp
}

pub(crate) fn make_precondition_failure_operation(
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
  status.set_code(grpcio::RpcStatusCode::FAILED_PRECONDITION.into());
  status.mut_details().push(make_any_proto(&{
    let mut precondition_failure = bazel_protos::error_details::PreconditionFailure::new();
    for violation in violations.into_iter() {
      precondition_failure.mut_violations().push(violation);
    }
    precondition_failure
  }));
  status
}

pub(crate) async fn run_cmd_runner<R: crate::CommandRunner>(
  request: MultiPlatformProcess,
  command_runner: R,
  store: Store,
) -> Result<RemoteTestResult, String> {
  let original = command_runner.run(request, Context::default()).await?;
  let stdout_bytes: Vec<u8> = store
    .load_file_bytes_with(original.stdout_digest, |bytes| bytes.into())
    .await?
    .unwrap()
    .0;
  let stderr_bytes: Vec<u8> = store
    .load_file_bytes_with(original.stderr_digest, |bytes| bytes.into())
    .await?
    .unwrap()
    .0;
  Ok(RemoteTestResult {
    original,
    stdout_bytes,
    stderr_bytes,
  })
}

async fn run_command_remote2(
  address: String,
  request: MultiPlatformProcess,
) -> Result<RemoteTestResult, String> {
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let (command_runner, store) = create_command_runner(
    address,
    &cas,
    Duration::from_millis(0),
    Duration::from_secs(0),
    Platform::Linux,
  );
  let original = command_runner.run(request, Context::default()).await?;

  let stdout_bytes: Vec<u8> = store
    .load_file_bytes_with(original.stdout_digest, |bytes| bytes.into())
    .await?
    .unwrap()
    .0;
  let stderr_bytes: Vec<u8> = store
    .load_file_bytes_with(original.stderr_digest, |bytes| bytes.into())
    .await?
    .unwrap()
    .0;
  Ok(RemoteTestResult {
    original,
    stdout_bytes,
    stderr_bytes,
  })
}

fn create_command_runner(
  address: String,
  cas: &mock::StubCAS,
  backoff_incremental_wait: Duration,
  backoff_max_wait: Duration,
  platform: Platform,
) -> (CommandRunner, Store) {
  let runtime = task_executor::Executor::new(Handle::current());
  let store_dir = TempDir::new().unwrap();
  let store = make_store(store_dir.path(), cas, runtime.clone());
  let command_runner = CommandRunner::new(
    &address,
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store.clone(),
    platform,
    runtime,
    Duration::from_secs(1), // We use a low queue_buffer_time to ensure that tests do not take too long.
    backoff_incremental_wait,
    backoff_max_wait,
  )
  .expect("Failed to make command runner");
  (command_runner, store)
}

pub(crate) fn make_store(
  store_dir: &Path,
  cas: &mock::StubCAS,
  executor: task_executor::Executor,
) -> Store {
  Store::with_remote(
    executor,
    store_dir,
    vec![cas.address()],
    None,
    None,
    None,
    1,
    10 * 1024 * 1024,
    Duration::from_secs(1),
    store::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .expect("Failed to make store")
}

async fn extract_execute_response(
  operation: bazel_protos::operations::Operation,
  timeout_has_elapsed: bool,
  remote_platform: Platform,
) -> Result<RemoteTestResult, ExecutionError> {
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let (command_runner, store) = create_command_runner(
    "".to_owned(),
    &cas,
    Duration::from_millis(0),
    Duration::from_secs(0),
    remote_platform,
  );

  let original = command_runner
    .extract_execute_response(
      OperationOrStatus::Operation(operation),
      timeout_has_elapsed,
      &mut ExecutionHistory::default(),
    )
    .compat()
    .await?;

  let stdout_bytes: Vec<u8> = store
    .load_file_bytes_with(original.stdout_digest, |bytes| bytes.into())
    .await
    .unwrap()
    .unwrap()
    .0;

  let stderr_bytes: Vec<u8> = store
    .load_file_bytes_with(original.stderr_digest, |bytes| bytes.into())
    .await
    .unwrap()
    .unwrap()
    .0;

  Ok(RemoteTestResult {
    original,
    stdout_bytes,
    stderr_bytes,
  })
}

async fn extract_output_files_from_response(
  execute_response: &bazel_protos::remote_execution::ExecuteResponse,
) -> Result<Digest, String> {
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let executor = task_executor::Executor::new(Handle::current());
  let store_dir = TempDir::new().unwrap();
  let store = make_store(store_dir.path(), &cas, executor.clone());
  crate::remote::extract_output_files(store, &execute_response)
    .compat()
    .await
}

pub(crate) fn make_any_proto(message: &dyn Message) -> protobuf::well_known_types::Any {
  let mut any = protobuf::well_known_types::Any::new();
  any.set_type_url(format!(
    "type.googleapis.com/{}",
    message.descriptor().full_name()
  ));
  any.set_value(message.write_to_bytes().expect("Error serializing proto"));
  any
}

pub(crate) fn missing_preconditionfailure_violation(
  digest: &Digest,
) -> bazel_protos::error_details::PreconditionFailure_Violation {
  {
    let mut violation = bazel_protos::error_details::PreconditionFailure_Violation::new();
    violation.set_field_type("MISSING".to_owned());
    violation.set_subject(format!("blobs/{}/{}", digest.0, digest.1));
    violation
  }
}

pub(crate) fn assert_contains(haystack: &str, needle: &str) {
  assert!(
    haystack.contains(needle),
    "{:?} should contain {:?}",
    haystack,
    needle
  )
}

pub(crate) fn cat_roland_request() -> MultiPlatformProcess {
  let req = Process {
    argv: owned_string_vec(&["/bin/cat", "roland"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: TestDirectory::containing_roland().digest(),
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "cat a roland".to_string(),
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  };
  req.into()
}

pub(crate) fn echo_roland_request() -> MultiPlatformProcess {
  let req = Process {
    argv: owned_string_vec(&["/bin/echo", "meoooow"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "unleash a roaring meow".to_string(),
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  };
  req.into()
}

pub(crate) fn empty_request_metadata() -> ProcessMetadata {
  ProcessMetadata {
    instance_name: None,
    cache_key_gen_version: None,
    platform_properties: vec![],
  }
}

pub(crate) fn assert_cancellation_requests(
  mock_server: &mock::execution_server::TestServer,
  expected: Vec<String>,
) {
  let cancels = mock_server
    .mock_responder
    .cancelation_requests
    .lock()
    .iter()
    .map(|req| req.get_name().to_owned())
    .collect::<Vec<_>>();
  assert_eq!(expected, cancels);
}

fn one_second() -> Option<Duration> {
  Some(Duration::from_millis(1000))
}
