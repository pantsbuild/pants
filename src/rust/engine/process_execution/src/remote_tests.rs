use bazel_protos;
use bazel_protos::operations::Operation;
use bazel_protos::remote_execution::ExecutedActionMetadata;
use bytes::Bytes;
use futures01::{future, Future};
use grpcio;
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use mock;
use protobuf::{self, Message, ProtobufEnum};
use spectral::{assert_that, string::StrAssertions};
use std::convert::TryInto;
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use testutil::{as_bytes, owned_string_vec};

use crate::remote::{CommandRunner, ExecutionError, ExecutionHistory, OperationOrStatus};
use crate::{
  CommandRunner as CommandRunnerTrait, Context, ExecuteProcessRequest,
  ExecuteProcessRequestMetadata, FallibleExecuteProcessResult, MultiPlatformExecuteProcessRequest,
  Platform,
};
use maplit::{btreemap, hashset};
use mock::execution_server::MockOperation;
use protobuf::well_known_types::Timestamp;
use spectral::prelude::*;
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::iter::{self, FromIterator};
use std::ops::Sub;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use tokio::timer::Delay;
use workunit_store::{WorkUnit, WorkUnitStore};

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

/// This test checks that `unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule`
/// is ignored for remoting by showing EPR with different digests of
/// `unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule`
/// end up having the same bazel_protos::remote_execution::ExecuteRequest.
#[test]
fn local_only_scratch_files_ignored() {
  let input_directory = TestDirectory::containing_roland();
  let req1 = ExecuteProcessRequest {
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
    timeout: Duration::from_millis(1000),
    description: "some description".to_owned(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
    is_nailgunnable: false,
  };

  let req2 = ExecuteProcessRequest {
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
    timeout: Duration::from_millis(1000),
    description: "some description".to_owned(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      TestDirectory::containing_falcons_dir().digest(),
    jdk_home: None,
    target_platform: Platform::None,
    is_nailgunnable: false,
  };

  assert_eq!(
    crate::remote::make_execute_request(&req1, empty_request_metadata()),
    crate::remote::make_execute_request(&req2, empty_request_metadata()),
  );
}

#[test]
fn make_execute_request() {
  let input_directory = TestDirectory::containing_roland();
  let req = ExecuteProcessRequest {
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
    timeout: Duration::from_millis(1000),
    description: "some description".to_owned(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
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

#[test]
fn make_execute_request_with_instance_name() {
  let input_directory = TestDirectory::containing_roland();
  let req = ExecuteProcessRequest {
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
    timeout: Duration::from_millis(1000),
    description: "some description".to_owned(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
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
  want_execute_request.set_instance_name("dark-tower".to_owned());
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
    crate::remote::make_execute_request(
      &req,
      ExecuteProcessRequestMetadata {
        instance_name: Some("dark-tower".to_owned()),
        cache_key_gen_version: None,
        platform_properties: vec![],
      }
    ),
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
    timeout: Duration::from_millis(1000),
    description: "some description".to_owned(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
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
        "c803d479ce49fc85fe5dfe55177594d9957713192b011459cbd3532982c388f5",
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
        "a56e51451c48a993ba7b0e5051f53618562f2b25be93e06171d819b9104cc96c",
      )
      .unwrap(),
      141,
    ))
      .into(),
  );

  assert_eq!(
    crate::remote::make_execute_request(
      &req,
      ExecuteProcessRequestMetadata {
        instance_name: None,
        cache_key_gen_version: Some("meep".to_owned()),
        platform_properties: vec![],
      }
    ),
    Ok((want_action, want_command, want_execute_request))
  );
}

#[test]
fn make_execute_request_with_jdk() {
  let input_directory = TestDirectory::containing_roland();
  let req = ExecuteProcessRequest {
    argv: owned_string_vec(&["/bin/echo", "yo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: input_directory.digest(),
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Duration::from_millis(1000),
    description: "some description".to_owned(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: Some(PathBuf::from("/tmp")),
    target_platform: Platform::None,
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

#[test]
fn make_execute_request_with_jdk_and_extra_platform_properties() {
  let input_directory = TestDirectory::containing_roland();
  let req = ExecuteProcessRequest {
    argv: owned_string_vec(&["/bin/echo", "yo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: input_directory.digest(),
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Duration::from_millis(1000),
    description: "some description".to_owned(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: Some(PathBuf::from("/tmp")),
    target_platform: Platform::None,
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
    property.set_name("Multi".to_owned());
    property.set_value("dos".to_owned());
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
    property.set_name("target_platform".to_owned());
    property.set_value("none".to_owned());
    property
  });

  let mut want_action = bazel_protos::remote_execution::Action::new();
  want_action.set_command_digest(
    (&Digest(
      Fingerprint::from_hex_string(
        "6c63c44ac364729d371931a091cc8379e32d021e06df52ab5f8461118d837e78",
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
        "5246770d23d09dc7d145e19d3a7b8233fc42316115fbc5420dfe501fb684e5e9",
      )
      .unwrap(),
      140,
    ))
      .into(),
  );

  assert_eq!(
    crate::remote::make_execute_request(
      &req,
      ExecuteProcessRequestMetadata {
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

#[test]
fn server_rejecting_execute_request_gives_error() {
  let execute_request = echo_foo_request();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        "wrong-command".to_string(),
        crate::remote::make_execute_request(
          &ExecuteProcessRequest {
            argv: owned_string_vec(&["/bin/echo", "-n", "bar"]),
            env: BTreeMap::new(),
            working_directory: None,
            input_files: EMPTY_DIGEST,
            output_files: BTreeSet::new(),
            output_directories: BTreeSet::new(),
            timeout: Duration::from_millis(1000),
            description: "wrong command".to_string(),
            unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
              hashing::EMPTY_DIGEST,
            jdk_home: None,
            target_platform: Platform::None,
            is_nailgunnable: false,
          },
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        vec![],
      ),
      None,
    )
  };

  let error = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");
  assert_that(&error).contains("InvalidArgument");
  assert_that(&error).contains("Did not expect this request");
}

#[test]
fn successful_execution_after_one_getoperation() {
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request).unwrap();

  assert_eq!(
    result.without_execution_attempts(),
    FallibleExecuteProcessResult {
      stdout: as_bytes("foo"),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
    }
  );

  assert_cancellation_requests(&mock_server, vec![]);
}

#[test]
fn retries_retriable_errors() {
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        vec![
          make_incomplete_operation(&op_name),
          make_retryable_operation_failure(),
          make_incomplete_operation(&op_name),
          make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        ],
      ),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request).unwrap();

  assert_eq!(
    result.without_execution_attempts(),
    FallibleExecuteProcessResult {
      stdout: as_bytes("foo"),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
    }
  );

  assert_cancellation_requests(&mock_server, vec![]);
}

#[test]
fn gives_up_after_many_retriable_errors() {
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        vec![
          make_incomplete_operation(&op_name),
          make_retryable_operation_failure(),
          make_incomplete_operation(&op_name),
          make_retryable_operation_failure(),
          make_incomplete_operation(&op_name),
          make_retryable_operation_failure(),
          make_incomplete_operation(&op_name),
          make_retryable_operation_failure(),
          make_incomplete_operation(&op_name),
          make_retryable_operation_failure(),
        ],
      ),
      None,
    )
  };

  let err = run_command_remote(mock_server.address(), execute_request).unwrap_err();

  assert_that!(err).contains("Gave up");
  assert_that!(err).contains("appears to be lost");

  assert_cancellation_requests(&mock_server, vec![]);
}

#[test]
pub fn sends_headers() {
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
      None,
    )
  };
  let cas = mock::StubCAS::empty();
  let runtime = task_executor::Executor::new();
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
    workunit_store: WorkUnitStore::default(),
    build_id: String::from("marmosets"),
  };
  tokio::runtime::Runtime::new()
    .unwrap()
    .block_on(command_runner.run(execute_request, context))
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
      output_directory: EMPTY_DIGEST,
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
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
    }
  );
}

#[test]
fn ensure_inline_stdio_is_stored() {
  let runtime = task_executor::Executor::new();

  let test_stdout = TestData::roland();
  let test_stderr = TestData::catnip();

  let mock_server = {
    let op_name = "cat".to_owned();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &echo_roland_request().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        vec![make_successful_operation(
          &op_name.clone(),
          StdoutType::Raw(test_stdout.string()),
          StderrType::Raw(test_stderr.string()),
          0,
        )],
      ),
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
    store,
    Platform::Linux,
    runtime.clone(),
    Duration::from_secs(0),
    Duration::from_millis(0),
    Duration::from_secs(0),
  )
  .unwrap();
  let result = runtime
    .block_on(cmd_runner.run(echo_roland_request(), Context::default()))
    .unwrap();
  assert_eq!(
    result.without_execution_attempts(),
    FallibleExecuteProcessResult {
      stdout: test_stdout.bytes(),
      stderr: test_stderr.bytes(),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
    }
  );

  let local_store =
    Store::local_only(runtime.clone(), &store_dir_path).expect("Error creating local store");
  {
    assert_eq!(
      runtime
        .block_on(local_store.load_file_bytes_with(
          test_stdout.digest(),
          |v| v,
          WorkUnitStore::new()
        ))
        .unwrap()
        .unwrap()
        .0,
      test_stdout.bytes()
    );
    assert_eq!(
      runtime
        .block_on(local_store.load_file_bytes_with(
          test_stderr.digest(),
          |v| v,
          WorkUnitStore::new()
        ))
        .unwrap()
        .unwrap()
        .0,
      test_stderr.bytes()
    );
  }
}

#[test]
fn successful_execution_after_four_getoperations() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request).unwrap();

  assert_eq!(
    result.without_execution_attempts(),
    FallibleExecuteProcessResult {
      stdout: as_bytes("foo"),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
    }
  );
}

#[test]
fn timeout_after_sufficiently_delayed_getoperations() {
  let request_timeout = Duration::new(1, 0);
  // The request should timeout after 2 seconds, with 1 second due to the queue_buffer_time and
  // 1 due to the request_timeout.
  let delayed_operation_time = Duration::new(2, 500);

  let execute_request = ExecuteProcessRequest {
    argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: request_timeout,
    description: "echo-a-foo".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
    is_nailgunnable: false,
  };

  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(&execute_request, empty_request_metadata())
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          make_delayed_incomplete_operation(&op_name, delayed_operation_time),
        ],
      ),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request.into()).unwrap();
  assert_eq!(result.exit_code, -15);
  let error_msg = String::from_utf8(result.stdout.to_vec()).unwrap();
  assert_that(&error_msg).contains("Exceeded timeout");
  assert_that(&error_msg).contains("echo-a-foo");
  assert_eq!(result.execution_attempts.len(), 1);
  let maybe_execution_duration = result.execution_attempts[0].remote_execution;
  assert!(maybe_execution_duration.is_some());
  assert_that(&maybe_execution_duration.unwrap()).is_greater_than_or_equal_to(request_timeout);

  assert_cancellation_requests(&mock_server, vec![op_name.to_owned()]);
}

#[test]
#[ignore] // https://github.com/pantsbuild/pants/issues/8405
fn dropped_request_cancels() {
  let request_timeout = Duration::new(10, 0);
  let delayed_operation_time = Duration::new(5, 0);

  let execute_request = ExecuteProcessRequest {
    argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: request_timeout,
    description: "echo-a-foo".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
    is_nailgunnable: false,
  };

  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(&execute_request, empty_request_metadata())
          .unwrap()
          .2,
        vec![
          make_incomplete_operation(&op_name),
          make_delayed_incomplete_operation(&op_name, delayed_operation_time),
        ],
      ),
      None,
    )
  };

  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let command_runner = create_command_runner(
    mock_server.address(),
    &cas,
    Duration::from_millis(0),
    Duration::from_secs(0),
  );
  let mut runtime = tokio::runtime::Runtime::new().unwrap();

  let successful_mock_result = FallibleExecuteProcessResult {
    stdout: as_bytes("foo-fast"),
    stderr: as_bytes(""),
    exit_code: 0,
    output_directory: EMPTY_DIGEST,
    execution_attempts: vec![],
  };

  let run_future = command_runner.run(execute_request.into(), Context::default());
  let faster_future = Delay::new(Instant::now() + Duration::from_secs(1))
    .map_err(|err| format!("Error from timer: {}", err))
    .map({
      let successful_mock_result = successful_mock_result.clone();
      |_| successful_mock_result
    });

  let result = runtime
    .block_on(
      run_future
        .select(faster_future)
        .map(|(result, _future)| result)
        .map_err(|(err, _future)| err),
    )
    .unwrap();

  assert_eq!(result.without_execution_attempts(), successful_mock_result);

  runtime.shutdown_on_idle().wait().unwrap();

  assert_cancellation_requests(&mock_server, vec![op_name.to_owned()]);
}

#[test]
fn retry_for_cancelled_channel() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request).unwrap();

  assert_eq!(
    result.without_execution_attempts(),
    FallibleExecuteProcessResult {
      stdout: as_bytes("foo"),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
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
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
      None,
    )
  };

  run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");
}

#[test]
fn initial_response_error() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");

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
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");

  assert_eq!(result, "INTERNAL: Something went wrong");

  assert_cancellation_requests(&mock_server, vec![]);
}

#[test]
fn initial_response_missing_response_and_error() {
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        vec![MockOperation::new({
          let mut op = bazel_protos::operations::Operation::new();
          op.set_name(op_name.to_string());
          op.set_done(true);
          op
        })],
      ),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");

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
        crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request).expect_err("Want Err");

  assert_eq!(result, "Operation finished but no response supplied");
}

#[test]
fn execute_missing_file_uploads_if_known() {
  let runtime = task_executor::Executor::new();

  let roland = TestData::roland();

  let mock_server = {
    let op_name = "cat".to_owned();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &cat_roland_request().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
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
  runtime
    .block_on(store.store_file_bytes(roland.bytes(), false))
    .expect("Saving file bytes to store");
  runtime
    .block_on(store.record_directory(&TestDirectory::containing_roland().directory(), false))
    .expect("Saving directory bytes to store");
  let command_runner = CommandRunner::new(
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

  let result = runtime
    .block_on(command_runner.run(cat_roland_request(), Context::default()))
    .unwrap();
  assert_eq!(
    result.without_execution_attempts(),
    FallibleExecuteProcessResult {
      stdout: roland.bytes(),
      stderr: Bytes::from(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
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

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &cat_roland_request().try_into().unwrap(),
          empty_request_metadata(),
        )
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
      ),
      None,
    )
  };

  let store_dir = TempDir::new().unwrap();
  let cas = mock::StubCAS::builder()
    .directory(&TestDirectory::containing_roland())
    .build();
  let runtime = task_executor::Executor::new();
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
    .wait()
    .expect("Saving file bytes to store");

  let result = CommandRunner::new(
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
  .unwrap()
  .run(cat_roland_request(), Context::default())
  .wait();
  assert_eq!(
    result,
    Ok(FallibleExecuteProcessResult {
      stdout: roland.bytes(),
      stderr: Bytes::from(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
    })
  );
  {
    let blobs = cas.blobs.lock();
    assert_eq!(blobs.get(&roland.fingerprint()), Some(&roland.bytes()));
  }

  assert_cancellation_requests(&mock_server, vec![]);
}

#[test]
fn execute_missing_file_errors_if_unknown() {
  let missing_digest = TestDirectory::containing_roland().digest();

  let mock_server = {
    let op_name = "cat".to_owned();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(
        op_name.clone(),
        crate::remote::make_execute_request(
          &cat_roland_request().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        // We won't get as far as trying to run the operation, so don't expect any requests whose
        // responses we would need to stub.
        vec![],
      ),
      None,
    )
  };

  let store_dir = TempDir::new().unwrap();
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let runtime = task_executor::Executor::new();
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

  let error = runtime
    .block_on(runner.run(cat_roland_request(), Context::default()))
    .expect_err("Want error");
  assert_contains(&error, &format!("{}", missing_digest.0));
}

#[test]
fn format_error_complete() {
  let mut error = bazel_protos::status::Status::new();
  error.set_code(bazel_protos::code::Code::CANCELLED.value());
  error.set_message("Oops, oh well!".to_string());
  assert_eq!(
    crate::remote::format_error(&error),
    "CANCELLED: Oops, oh well!".to_string()
  );
}

#[test]
fn extract_execute_response_unknown_code() {
  let mut error = bazel_protos::status::Status::new();
  error.set_code(555);
  error.set_message("Oops, oh well!".to_string());
  assert_eq!(
    crate::remote::format_error(&error),
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

  let digest = crate::remote::digest(&command).unwrap();

  assert_eq!(
    &digest.0.to_hex(),
    "a32cd427e5df6a998199266681692989f56c19cabd1cc637bdd56ae2e62619b4"
  );
  assert_eq!(digest.1, 32)
}

#[test]
fn wait_between_request_1_retry() {
  // wait at least 100 milli for one retry
  {
    let execute_request = echo_foo_request();
    let mock_server = {
      let op_name = "gimme-foo".to_string();
      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          op_name.clone(),
          crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
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
        ),
        None,
      )
    };
    let cas = mock::StubCAS::empty();
    let command_runner = create_command_runner(
      mock_server.address(),
      &cas,
      Duration::from_millis(100),
      Duration::from_secs(1),
    );
    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    runtime
      .block_on(command_runner.run(execute_request, Context::default()))
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

#[test]
fn wait_between_request_3_retry() {
  // wait at least 50 + 100 + 150 = 300 milli for 3 retries.
  {
    let execute_request = echo_foo_request();
    let mock_server = {
      let op_name = "gimme-foo".to_string();
      mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(
          op_name.clone(),
          crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
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
        ),
        None,
      )
    };
    let cas = mock::StubCAS::empty();
    let command_runner = create_command_runner(
      mock_server.address(),
      &cas,
      Duration::from_millis(50),
      Duration::from_secs(5),
    );
    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    runtime
      .block_on(command_runner.run(execute_request, Context::default()))
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

#[test]
fn extract_output_files_from_response_no_prefix() {
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
    extract_output_files_from_response(&execute_response),
    Ok(TestDirectory::containing_roland().digest())
  )
}

fn workunits_with_constant_span_id(workunit_store: &WorkUnitStore) -> HashSet<WorkUnit> {
  workunit_store
    .get_workunits()
    .lock()
    .workunits
    .iter()
    .map(|workunit| WorkUnit {
      span_id: String::from("ignore"),
      ..workunit.clone()
    })
    .collect()
}

#[test]
fn remote_workunits_are_stored() {
  let workunit_store = WorkUnitStore::new();
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
  let command_runner = create_command_runner(
    "".to_owned(),
    &cas,
    std::time::Duration::from_millis(0),
    std::time::Duration::from_secs(0),
  );

  let mut runtime = tokio::runtime::Runtime::new().unwrap();

  let workunit_store_2 = workunit_store.clone();
  runtime
    .block_on(future::lazy(move || {
      command_runner.extract_execute_response(
        OperationOrStatus::Operation(operation),
        &mut ExecutionHistory::default(),
        workunit_store_2,
      )
    }))
    .unwrap();

  let got_workunits = workunits_with_constant_span_id(&workunit_store);

  use concrete_time::Duration;
  use concrete_time::TimeSpan;

  let want_workunits = hashset! {
    WorkUnit {
      name: String::from("remote execution action scheduling"),
      time_span: TimeSpan {
          start: Duration::new(0, 0),
          duration: Duration::new(1, 0),
      },
      span_id: String::from("ignore"),
      parent_id: None,
    },
    WorkUnit {
      name: String::from("remote execution worker input fetching"),
      time_span: TimeSpan {
          start: Duration::new(2, 0),
          duration: Duration::new(1, 0),
      },
      span_id: String::from("ignore"),
      parent_id: None,
    },
    WorkUnit {
      name: String::from("remote execution worker command executing"),
      time_span: TimeSpan {
          start: Duration::new(4, 0),
          duration: Duration::new(1, 0),
      },
      span_id: String::from("ignore"),
      parent_id: None,
    },
    WorkUnit {
      name: String::from("remote execution worker output uploading"),
      time_span: TimeSpan {
          start: Duration::new(6, 0),
          duration: Duration::new(1, 0),
      },
      span_id: String::from("ignore"),
      parent_id: None,
    }
  };

  assert!(got_workunits.is_superset(&want_workunits));
}

pub fn echo_foo_request() -> MultiPlatformExecuteProcessRequest {
  let req = ExecuteProcessRequest {
    argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Duration::from_millis(5000),
    description: "echo a foo".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
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

fn make_incomplete_operation(operation_name: &str) -> MockOperation {
  let mut op = bazel_protos::operations::Operation::new();
  op.set_name(operation_name.to_string());
  op.set_done(false);
  MockOperation::new(op)
}

fn make_retryable_operation_failure() -> MockOperation {
  let mut status = bazel_protos::status::Status::new();
  status.set_code(grpcio::RpcStatusCode::Aborted as i32);
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

fn make_successful_operation(
  operation_name: &str,
  stdout: StdoutType,
  stderr: StderrType,
  exit_code: i32,
) -> MockOperation {
  let op =
    make_successful_operation_with_maybe_metadata(operation_name, stdout, stderr, exit_code, None);
  MockOperation::new(op)
}

fn make_successful_operation_with_metadata(
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
  request: MultiPlatformExecuteProcessRequest,
) -> Result<FallibleExecuteProcessResult, String> {
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let command_runner = create_command_runner(
    address,
    &cas,
    Duration::from_millis(0),
    Duration::from_secs(0),
  );
  let mut runtime = tokio::runtime::Runtime::new().unwrap();
  runtime.block_on(command_runner.run(request, Context::default()))
}

fn create_command_runner(
  address: String,
  cas: &mock::StubCAS,
  backoff_incremental_wait: Duration,
  backoff_max_wait: Duration,
) -> CommandRunner {
  let runtime = task_executor::Executor::new();
  let store_dir = TempDir::new().unwrap();
  let store = make_store(store_dir.path(), cas, runtime.clone());
  CommandRunner::new(
    &address,
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store,
    Platform::Linux,
    runtime,
    Duration::from_secs(1), // We use a low queue_buffer_time to ensure that tests do not take too long.
    backoff_incremental_wait,
    backoff_max_wait,
  )
  .expect("Failed to make command runner")
}

fn make_store(store_dir: &Path, cas: &mock::StubCAS, executor: task_executor::Executor) -> Store {
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

fn extract_execute_response(
  operation: bazel_protos::operations::Operation,
) -> Result<FallibleExecuteProcessResult, ExecutionError> {
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let command_runner = create_command_runner(
    "".to_owned(),
    &cas,
    Duration::from_millis(0),
    Duration::from_secs(0),
  );

  let mut runtime = tokio::runtime::Runtime::new().unwrap();

  runtime.block_on(command_runner.extract_execute_response(
    OperationOrStatus::Operation(operation),
    &mut ExecutionHistory::default(),
    WorkUnitStore::new(),
  ))
}

fn extract_output_files_from_response(
  execute_response: &bazel_protos::remote_execution::ExecuteResponse,
) -> Result<Digest, String> {
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let executor = task_executor::Executor::new();
  let store_dir = TempDir::new().unwrap();
  let store = make_store(store_dir.path(), &cas, executor.clone());
  executor.block_on(crate::remote::extract_output_files(
    store,
    &execute_response,
    WorkUnitStore::new(),
  ))
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

fn cat_roland_request() -> MultiPlatformExecuteProcessRequest {
  let req = ExecuteProcessRequest {
    argv: owned_string_vec(&["/bin/cat", "roland"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: TestDirectory::containing_roland().digest(),
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Duration::from_millis(1000),
    description: "cat a roland".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
    is_nailgunnable: false,
  };
  req.into()
}

fn echo_roland_request() -> MultiPlatformExecuteProcessRequest {
  let req = ExecuteProcessRequest {
    argv: owned_string_vec(&["/bin/echo", "meoooow"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Duration::from_millis(1000),
    description: "unleash a roaring meow".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
    is_nailgunnable: false,
  };
  req.into()
}

fn empty_request_metadata() -> ExecuteProcessRequestMetadata {
  ExecuteProcessRequestMetadata {
    instance_name: None,
    cache_key_gen_version: None,
    platform_properties: vec![],
  }
}

fn assert_cancellation_requests(
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
