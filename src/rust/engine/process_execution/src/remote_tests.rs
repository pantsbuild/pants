use std::collections::{BTreeMap, HashSet};
use std::convert::TryInto;
use std::path::{Path, PathBuf};
use std::time::Duration;

use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use bazel_protos::gen::google::longrunning::Operation;
use bytes::Bytes;
use grpc_util::prost::MessageExt;
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use maplit::{btreemap, hashset};
use mock::execution_server::{ExpectedAPICall, MockOperation};
use prost::Message;
use remexec::ExecutedActionMetadata;
use spectral::prelude::*;
use spectral::{assert_that, string::StrAssertions};
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory, TestTree};
use testutil::{owned_string_vec, relative_paths};
use workunit_store::{WorkunitState, WorkunitStore};

use crate::remote::{digest, CommandRunner, ExecutionError, OperationOrStatus};
use crate::{
  CommandRunner as CommandRunnerTrait, Context, FallibleProcessResultWithPlatform,
  MultiPlatformProcess, Platform, Process, ProcessCacheScope, ProcessMetadata,
};
use std::any::type_name;
use std::io::Cursor;
use tonic::{Code, Status};

const OVERALL_DEADLINE_SECS: Duration = Duration::from_secs(10 * 60);
const RETRY_INTERVAL: Duration = Duration::from_micros(0);

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
    output_files: relative_paths(&["path/to/file", "other/file"]).collect(),
    output_directories: relative_paths(&["directory/name"]).collect(),
    timeout: None,
    description: "some description".to_owned(),
    level: log::Level::Info,
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    platform_constraint: None,
    is_nailgunnable: false,
    execution_slot_variable: None,
    cache_scope: ProcessCacheScope::Always,
  };

  let want_command = remexec::Command {
    arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
    environment_variables: vec![
      remexec::command::EnvironmentVariable {
        name: crate::remote::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
        value: "none".to_owned(),
      },
      remexec::command::EnvironmentVariable {
        name: "SOME".to_owned(),
        value: "value".to_owned(),
      },
    ],
    output_files: vec!["other/file".to_owned(), "path/to/file".to_owned()],
    output_directories: vec!["directory/name".to_owned()],
    platform: Some(remexec::Platform::default()),
    ..Default::default()
  };

  let want_action = remexec::Action {
    command_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "369820f9643feb39980c51fb6d35d59567256946ff3234a371cba8f4de95339c",
        )
        .unwrap(),
        115,
      ))
        .into(),
    ),
    input_root_digest: Some((&input_directory.digest()).into()),
    ..Default::default()
  };

  let want_execute_request = remexec::ExecuteRequest {
    action_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "51cda3b6c18ddd47005162010e898b20faf842b3ba1a840d1a619bd962d53192",
        )
        .unwrap(),
        140,
      ))
        .into(),
    ),
    ..Default::default()
  };

  assert_eq!(
    crate::remote::make_execute_request(&req, ProcessMetadata::default()),
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
    output_files: relative_paths(&["path/to/file", "other/file"]).collect(),
    output_directories: relative_paths(&["directory/name"]).collect(),
    timeout: None,
    description: "some description".to_owned(),
    level: log::Level::Info,
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    platform_constraint: None,
    is_nailgunnable: false,
    execution_slot_variable: None,
    cache_scope: ProcessCacheScope::Always,
  };

  let want_command = remexec::Command {
    arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
    environment_variables: vec![
      remexec::command::EnvironmentVariable {
        name: crate::remote::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
        value: "none".to_owned(),
      },
      remexec::command::EnvironmentVariable {
        name: "SOME".to_owned(),
        value: "value".to_owned(),
      },
    ],
    output_files: vec!["other/file".to_owned(), "path/to/file".to_owned()],
    output_directories: vec!["directory/name".to_owned()],
    platform: Some(remexec::Platform {
      properties: vec![remexec::platform::Property {
        name: "target_platform".to_owned(),
        value: "apple-2e".to_owned(),
      }],
    }),
    ..Default::default()
  };

  let want_action = remexec::Action {
    command_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "ce536af7c6334e325a99507409535d50acf05338d4cbdd031425bdaa55a87d6d",
        )
        .unwrap(),
        144,
      ))
        .into(),
    ),
    input_root_digest: Some((&input_directory.digest()).into()),
    ..Default::default()
  };

  let want_execute_request = remexec::ExecuteRequest {
    instance_name: "dark-tower".to_owned(),
    action_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "11cc69e6e2376c57a54a42db3d3dd22b2996a1527f976589d2d200623097b5c8",
        )
        .unwrap(),
        141,
      ))
        .into(),
    ),
    ..Default::default()
  };

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
    output_files: relative_paths(&["path/to/file", "other/file"]).collect(),
    output_directories: relative_paths(&["directory/name"]).collect(),
    timeout: None,
    description: "some description".to_owned(),
    level: log::Level::Info,
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    platform_constraint: None,
    is_nailgunnable: false,
    execution_slot_variable: None,
    cache_scope: ProcessCacheScope::Always,
  };

  let mut want_command = remexec::Command {
    arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
    environment_variables: vec![
      remexec::command::EnvironmentVariable {
        name: crate::remote::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
        value: "none".to_owned(),
      },
      remexec::command::EnvironmentVariable {
        name: crate::remote::CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_owned(),
        value: "meep".to_owned(),
      },
      remexec::command::EnvironmentVariable {
        name: "SOME".to_owned(),
        value: "value".to_owned(),
      },
    ],
    output_files: vec!["other/file".to_owned(), "path/to/file".to_owned()],
    output_directories: vec!["directory/name".to_owned()],
    platform: Some(remexec::Platform::default()),
    ..Default::default()
  };
  want_command
    .environment_variables
    .sort_by(|x, y| x.name.cmp(&y.name));

  let want_action = remexec::Action {
    command_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "09e54a4817a36e164a0e395fac36091fd5b4aac185b8bafa90842ac4aff92a34",
        )
        .unwrap(),
        152,
      ))
        .into(),
    ),
    input_root_digest: Some((&input_directory.digest()).into()),
    ..Default::default()
  };

  let want_execute_request = remexec::ExecuteRequest {
    action_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "dc554a1ed77588e1bac90896dcfeba255f8178ebc01893231415841109216944",
        )
        .unwrap(),
        141,
      ))
        .into(),
    ),
    ..Default::default()
  };

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
  let mut req = Process::new(owned_string_vec(&["/bin/echo", "yo"]));
  req.jdk_home = Some(PathBuf::from("/tmp"));
  req.description = "some description".to_owned();
  req.input_files = input_directory.digest();

  let want_command = remexec::Command {
    arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
    environment_variables: vec![remexec::command::EnvironmentVariable {
      name: crate::remote::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
      value: "none".to_owned(),
    }],
    platform: Some(remexec::Platform {
      properties: vec![remexec::platform::Property {
        name: "JDK_SYMLINK".to_owned(),
        value: ".jdk".to_owned(),
      }],
    }),
    ..Default::default()
  };

  let want_action = remexec::Action {
    command_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "9e969561212af080f0b6c346cdf954265a489f9c9fae63d11d61869174b13e29",
        )
        .unwrap(),
        79,
      ))
        .into(),
    ),
    input_root_digest: Some((&input_directory.digest()).into()),
    ..Default::default()
  };

  let want_execute_request = remexec::ExecuteRequest {
    action_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "f90182cd453f36577868fc05a605ac84c19882c18bd907ff241923d98a7bca1e",
        )
        .unwrap(),
        140,
      ))
        .into(),
    ),
    ..Default::default()
  };

  assert_eq!(
    crate::remote::make_execute_request(&req, ProcessMetadata::default()),
    Ok((want_action, want_command, want_execute_request))
  );
}

#[tokio::test]
async fn make_execute_request_with_jdk_and_extra_platform_properties() {
  let input_directory = TestDirectory::containing_roland();
  let mut req = Process::new(owned_string_vec(&["/bin/echo", "yo"]));
  req.input_files = input_directory.digest();
  req.description = "some description".to_owned();
  req.jdk_home = Some(PathBuf::from("/tmp"));

  let want_command = remexec::Command {
    arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
    environment_variables: vec![remexec::command::EnvironmentVariable {
      name: crate::remote::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
      value: "none".to_owned(),
    }],
    platform: Some(remexec::Platform {
      properties: vec![
        remexec::platform::Property {
          name: "FIRST".to_owned(),
          value: "foo".to_owned(),
        },
        remexec::platform::Property {
          name: "JDK_SYMLINK".to_owned(),
          value: ".jdk".to_owned(),
        },
        remexec::platform::Property {
          name: "Multi".to_owned(),
          value: "dos".to_owned(),
        },
        remexec::platform::Property {
          name: "Multi".to_owned(),
          value: "uno".to_owned(),
        },
        remexec::platform::Property {
          name: "last".to_owned(),
          value: "bar".to_owned(),
        },
      ],
    }),
    ..Default::default()
  };

  let want_action = remexec::Action {
    command_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "8d59966fac1f1a7c209ca33f8ca003ed3985b9835043fc114c45aaafa119a77b",
        )
        .unwrap(),
        134,
      ))
        .into(),
    ),
    input_root_digest: Some((&input_directory.digest()).into()),
    ..Default::default()
  };

  let want_execute_request = remexec::ExecuteRequest {
    action_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "190e7b28a9e32be6cb0beaad97d175c6882857991598de3585c91aec183b14b3",
        )
        .unwrap(),
        141,
      ))
        .into(),
    ),
    ..Default::default()
  };

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
    output_files: relative_paths(&["path/to/file", "other/file"]).collect(),
    output_directories: relative_paths(&["directory/name"]).collect(),
    timeout: one_second(),
    description: "some description".to_owned(),
    level: log::Level::Info,
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    platform_constraint: None,
    is_nailgunnable: false,
    execution_slot_variable: None,
    cache_scope: ProcessCacheScope::Always,
  };

  let want_command = remexec::Command {
    arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
    environment_variables: vec![
      remexec::command::EnvironmentVariable {
        name: crate::remote::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
        value: "none".to_owned(),
      },
      remexec::command::EnvironmentVariable {
        name: "SOME".to_owned(),
        value: "value".to_owned(),
      },
    ],
    output_files: vec!["other/file".to_owned(), "path/to/file".to_owned()],
    output_directories: vec!["directory/name".to_owned()],
    platform: Some(remexec::Platform::default()),
    ..Default::default()
  };

  let want_action = remexec::Action {
    command_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "369820f9643feb39980c51fb6d35d59567256946ff3234a371cba8f4de95339c",
        )
        .unwrap(),
        115,
      ))
        .into(),
    ),
    input_root_digest: Some((&input_directory.digest()).into()),
    timeout: Some(prost_types::Duration::from(Duration::from_secs(1))),
    ..Default::default()
  };

  let want_execute_request = remexec::ExecuteRequest {
    action_digest: Some(
      (&Digest::new(
        Fingerprint::from_hex_string(
          "151e4bfce1244eb7ae74ed09d8759088557d9c63fbaaa5fcca662998266f4b09",
        )
        .unwrap(),
        144,
      ))
        .into(),
    ),
    ..Default::default()
  };

  assert_eq!(
    crate::remote::make_execute_request(&req, ProcessMetadata::default()),
    Ok((want_action, want_command, want_execute_request))
  );
}

#[tokio::test]
async fn successful_with_only_call_to_execute() {
  WorkunitStore::setup_for_tests();
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    let (action, _, execute_request) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();
    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("")),
        },
        ExpectedAPICall::Execute {
          execute_request,
          stream_responses: Ok(vec![
            make_incomplete_operation(&op_name),
            make_successful_operation(
              &op_name,
              StdoutType::Raw("foo".to_owned()),
              StderrType::Raw("".to_owned()),
              0,
            ),
          ]),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn successful_after_reconnect_with_wait_execution() {
  WorkunitStore::setup_for_tests();
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    let (action, _, execute_request) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();
    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request,
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::WaitExecution {
          operation_name: op_name.clone(),
          stream_responses: Ok(vec![make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          )]),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn successful_after_reconnect_from_retryable_error() {
  WorkunitStore::setup_for_tests();
  let execute_request = echo_foo_request();
  let op_name_1 = "gimme-foo".to_string();
  let op_name_2 = "gimme-bar".to_string();

  let mock_server = {
    let (action, _, execute_request) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let execute_request_2 = execute_request.clone();

    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request,
          stream_responses: Ok(vec![
            make_incomplete_operation(&op_name_1),
            make_retryable_operation_failure(),
          ]),
        },
        ExpectedAPICall::Execute {
          execute_request: execute_request_2,
          stream_responses: Ok(vec![
            make_incomplete_operation(&op_name_2),
            make_successful_operation(
              &op_name_2,
              StdoutType::Raw("foo".to_owned()),
              StderrType::Raw("".to_owned()),
              0,
            ),
          ]),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn successful_served_from_action_cache() {
  WorkunitStore::setup_for_tests();
  let execute_request = echo_foo_request();

  let mock_server = {
    let (action, _, _) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let action_digest = digest(&action).unwrap();

    let action_result = make_action_result(
      StdoutType::Raw("foo".to_owned()),
      StderrType::Raw("".to_owned()),
      0,
      None,
    );

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![ExpectedAPICall::GetActionResult {
        action_digest,
        response: Ok(action_result),
      }]),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, EMPTY_DIGEST);
  assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn server_rejecting_execute_request_gives_error() {
  WorkunitStore::setup_for_tests();

  let execute_request = echo_foo_request();

  let mock_server = mock::execution_server::TestServer::new(
    mock::execution_server::MockExecution::new(vec![
      ExpectedAPICall::GetActionResult {
        action_digest: hashing::Digest::new(
          hashing::Fingerprint::from_hex_string(
            "bf10cd168ad711602f7a241cbcbc9a3d32497fdd1465d8a01d4549ee7d8ebc08",
          )
          .unwrap(),
          142,
        ),
        response: Err(Status::not_found("")),
      },
      ExpectedAPICall::Execute {
        execute_request: crate::remote::make_execute_request(
          &Process::new(owned_string_vec(&["/bin/echo", "-n", "bar"])),
          ProcessMetadata::default(),
        )
        .unwrap()
        .2,
        stream_responses: Err(Status::invalid_argument("".to_owned())),
      },
    ]),
    None,
  );

  let error = run_command_remote(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");
  assert_that(&error).contains("InvalidArgument");
  assert_that(&error).contains("Did not expect this request");
}

#[tokio::test]
async fn server_sending_triggering_timeout_with_deadline_exceeded() {
  WorkunitStore::setup_for_tests();

  let execute_request = echo_foo_request();

  let mock_server = {
    let (action, _, execute_request) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request,
          stream_responses: Err(Status::deadline_exceeded("")),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .expect("Should succeed, but with a failed process.");
  assert!(result.stdout().contains("user timeout"));
}

#[tokio::test]
async fn sends_headers() {
  WorkunitStore::setup_for_tests();

  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    let (action, _, execute_request) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request,
          stream_responses: Ok(vec![
            make_incomplete_operation(&op_name),
            make_successful_operation(
              &op_name,
              StdoutType::Raw("foo".to_owned()),
              StderrType::Raw("".to_owned()),
              0,
            ),
          ]),
        },
      ]),
      None,
    )
  };
  let cas = mock::StubCAS::empty();
  let runtime = task_executor::Executor::new();
  let store_dir = TempDir::new().unwrap();
  let store = Store::with_remote(
    runtime.clone(),
    store_dir,
    &cas.address(),
    None,
    None,
    BTreeMap::new(),
    10 * 1024 * 1024,
    Duration::from_secs(1),
    1,
  )
  .expect("Failed to make store");

  let command_runner = CommandRunner::new(
    &mock_server.address(),
    &mock_server.address(),
    ProcessMetadata::default(),
    None,
    btreemap! {
      String::from("cat") => String::from("roland"),
      String::from("authorization") => String::from("Bearer catnip-will-get-you-anywhere"),
    },
    store,
    Platform::Linux,
    OVERALL_DEADLINE_SECS,
    RETRY_INTERVAL,
  )
  .unwrap();
  let context = Context {
    workunit_store: WorkunitStore::new(false),
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
      let want_key = "google.devtools.remoteexecution.v1test.requestmetadata-bin";
      assert!(headers.contains_key(want_key));

      let bytes = headers.get_bin(want_key).unwrap().to_bytes().unwrap();
      let proto = remexec::RequestMetadata::decode(Cursor::new(bytes))
        .expect("Failed to parse metadata proto");

      assert_eq!(proto.tool_details.map(|x| x.tool_name).unwrap(), "pants");
      assert_eq!(proto.tool_invocation_id, "marmosets");
    }

    assert_eq!(headers.get("cat").unwrap().to_str().unwrap(), "roland");

    assert_eq!(
      headers.get("authorization").unwrap().to_str().unwrap(),
      "Bearer catnip-will-get-you-anywhere"
    );
  }
}

#[tokio::test]
async fn extract_response_with_digest_stdout() {
  WorkunitStore::setup_for_tests();

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
  WorkunitStore::setup_for_tests();

  let runtime = task_executor::Executor::new();

  let test_stdout = TestData::roland();
  let test_stderr = TestData::catnip();

  let mock_server = {
    let op_name = "cat".to_owned();

    let (action, _, execute_request) = crate::remote::make_execute_request(
      &echo_roland_request().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request,
          stream_responses: Ok(vec![
            make_incomplete_operation(&op_name),
            make_successful_operation(
              &op_name.clone(),
              StdoutType::Raw(test_stdout.string()),
              StderrType::Raw(test_stderr.string()),
              0,
            ),
          ]),
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
    &cas.address(),
    None,
    None,
    BTreeMap::new(),
    10 * 1024 * 1024,
    Duration::from_secs(1),
    1,
  )
  .expect("Failed to make store");

  let cmd_runner = CommandRunner::new(
    &mock_server.address(),
    &mock_server.address(),
    ProcessMetadata::default(),
    None,
    BTreeMap::new(),
    store.clone(),
    Platform::Linux,
    OVERALL_DEADLINE_SECS,
    RETRY_INTERVAL,
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
        .load_file_bytes_with(test_stdout.digest(), |v| Bytes::copy_from_slice(v))
        .await
        .unwrap()
        .unwrap()
        .0,
      test_stdout.bytes()
    );
    assert_eq!(
      local_store
        .load_file_bytes_with(test_stderr.digest(), |v| Bytes::copy_from_slice(v))
        .await
        .unwrap()
        .unwrap()
        .0,
      test_stderr.bytes()
    );
  }
}

#[tokio::test]
async fn bad_result_bytes() {
  WorkunitStore::setup_for_tests();
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
        execute_request: crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          ProcessMetadata::default(),
        )
        .unwrap()
        .2,
        stream_responses: Ok(vec![
          make_incomplete_operation(&op_name),
          MockOperation::new(Operation {
            name: op_name.clone(),
            done: true,
            result: Some(
              bazel_protos::gen::google::longrunning::operation::Result::Response(
                prost_types::Any {
                  type_url: "type.googleapis.com/build.bazel.remote.execution.v2.ExecuteResponse"
                    .into(),
                  value: vec![0x00, 0x00, 0x00],
                },
              ),
            ),
            ..Default::default()
          }),
        ]),
      }]),
      None,
    )
  };

  run_command_remote(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");
}

#[tokio::test]
async fn initial_response_error() {
  WorkunitStore::setup_for_tests();
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    let (action, _, execute_request) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request,
          stream_responses: Ok(vec![MockOperation::new({
            Operation {
              name: op_name.to_string(),
              done: true,
              result: Some(
                bazel_protos::gen::google::longrunning::operation::Result::Error(
                  bazel_protos::gen::google::rpc::Status {
                    code: Code::Internal as i32,
                    message: "Something went wrong".to_string(),
                    ..Default::default()
                  },
                ),
              ),
              ..Default::default()
            }
          })]),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");

  assert_eq!(result, "Internal: Something went wrong");
}

#[tokio::test]
async fn initial_response_missing_response_and_error() {
  WorkunitStore::setup_for_tests();
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "gimme-foo".to_string();

    let (action, _, execute_request) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request,
          stream_responses: Ok(vec![MockOperation::new({
            Operation {
              name: op_name.to_string(),
              done: true,
              ..Default::default()
            }
          })]),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");

  assert_eq!(result, "Operation finished but no response supplied");
}

#[tokio::test]
async fn fails_after_retry_limit_exceeded() {
  WorkunitStore::setup_for_tests();
  let execute_request = echo_foo_request();

  let mock_server = {
    let (action, _, execute_request) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request: execute_request.clone(),
          stream_responses: Ok(vec![make_retryable_operation_failure()]),
        },
        ExpectedAPICall::Execute {
          execute_request: execute_request.clone(),
          stream_responses: Ok(vec![make_retryable_operation_failure()]),
        },
        ExpectedAPICall::Execute {
          execute_request: execute_request.clone(),
          stream_responses: Ok(vec![make_retryable_operation_failure()]),
        },
        ExpectedAPICall::Execute {
          execute_request: execute_request.clone(),
          stream_responses: Ok(vec![make_retryable_operation_failure()]),
        },
        ExpectedAPICall::Execute {
          execute_request: execute_request.clone(),
          stream_responses: Ok(vec![make_retryable_operation_failure()]),
        },
        ExpectedAPICall::Execute {
          execute_request: execute_request.clone(),
          stream_responses: Ok(vec![make_retryable_operation_failure()]),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .expect_err("Expected error");

  assert_eq!(
    result,
    "Too many failures from server. The last error was: the bot running the task appears to be lost"
  );
}

#[tokio::test]
async fn fails_after_retry_limit_exceeded_with_stream_close() {
  WorkunitStore::setup_for_tests();
  let execute_request = echo_foo_request();

  let mock_server = {
    let op_name = "foo-bar".to_owned();
    let (action, _, execute_request) = crate::remote::make_execute_request(
      &execute_request.clone().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request: execute_request.clone(),
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::WaitExecution {
          operation_name: op_name.clone(),
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::WaitExecution {
          operation_name: op_name.clone(),
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::WaitExecution {
          operation_name: op_name.clone(),
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::WaitExecution {
          operation_name: op_name.clone(),
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
        ExpectedAPICall::WaitExecution {
          operation_name: op_name.clone(),
          stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
        },
      ]),
      None,
    )
  };

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .expect_err("Expected error");

  assert_eq!(
    result,
    "Too many failures from server. The last event was the server disconnecting with no error given."
  );
}

#[tokio::test]
async fn execute_missing_file_uploads_if_known() {
  WorkunitStore::setup_for_tests();
  let runtime = task_executor::Executor::new();

  let roland = TestData::roland();

  let mock_server = {
    let op_name = "cat".to_owned();

    let (action, _, execute_request) = crate::remote::make_execute_request(
      &cat_roland_request().try_into().unwrap(),
      ProcessMetadata::default(),
    )
    .unwrap();

    let action_digest = digest(&action).unwrap();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![
        ExpectedAPICall::GetActionResult {
          action_digest,
          response: Err(Status::not_found("".to_owned())),
        },
        ExpectedAPICall::Execute {
          execute_request,
          stream_responses: Ok(vec![
            make_incomplete_operation(&op_name),
            make_precondition_failure_operation(vec![missing_preconditionfailure_violation(
              &roland.digest(),
            )]),
          ]),
        },
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &cat_roland_request().try_into().unwrap(),
            ProcessMetadata::default(),
          )
          .unwrap()
          .2,
          stream_responses: Ok(vec![
            make_incomplete_operation(&op_name),
            make_successful_operation(
              "cat2",
              StdoutType::Raw(roland.string()),
              StderrType::Raw("".to_owned()),
              0,
            ),
          ]),
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
    &cas.address(),
    None,
    None,
    BTreeMap::new(),
    10 * 1024 * 1024,
    Duration::from_secs(1),
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
    &mock_server.address(),
    ProcessMetadata::default(),
    None,
    BTreeMap::new(),
    store.clone(),
    Platform::Linux,
    OVERALL_DEADLINE_SECS,
    RETRY_INTERVAL,
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
async fn execute_missing_file_errors_if_unknown() {
  WorkunitStore::setup_for_tests();
  let missing_digest = TestDirectory::containing_roland().digest();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![ExpectedAPICall::GetActionResult {
        action_digest: hashing::Digest::new(
          hashing::Fingerprint::from_hex_string(
            "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16",
          )
          .unwrap(),
          144,
        ),
        response: Err(Status::not_found("".to_owned())),
      }]),
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
    &cas.address(),
    None,
    None,
    BTreeMap::new(),
    10 * 1024 * 1024,
    Duration::from_secs(1),
    1,
  )
  .expect("Failed to make store");

  let runner = CommandRunner::new(
    &mock_server.address(),
    &mock_server.address(),
    ProcessMetadata::default(),
    None,
    BTreeMap::new(),
    store,
    Platform::Linux,
    OVERALL_DEADLINE_SECS,
    RETRY_INTERVAL,
  )
  .unwrap();

  let error = runner
    .run(cat_roland_request(), Context::default())
    .await
    .expect_err("Want error");
  assert_contains(&error, &format!("{}", missing_digest.hash));
}

#[tokio::test]
async fn extract_execute_response_success() {
  let wanted_exit_code = 17;
  let wanted_stdout = Bytes::from_static(b"roland");
  let wanted_stderr = Bytes::from_static(b"simba");

  let operation = Operation {
    name: "cat".to_owned(),
    done: true,
    result: Some(
      bazel_protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
        &remexec::ExecuteResponse {
          result: Some(remexec::ActionResult {
            exit_code: wanted_exit_code,
            stdout_raw: wanted_stdout.clone(),
            stderr_raw: wanted_stderr.clone(),
            output_files: vec![remexec::OutputFile {
              path: "cats/roland".into(),
              digest: Some((&TestData::roland().digest()).into()),
              is_executable: false,
              ..Default::default()
            }],
            ..Default::default()
          }),
          ..Default::default()
        },
        "bazel_protos::gen::",
      )),
    ),
    ..Default::default()
  };

  let result = extract_execute_response(operation, Platform::Linux)
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
async fn extract_execute_response_timeout() {
  let operation = Operation {
    name: "cat".to_owned(),
    done: true,
    result: Some(
      bazel_protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
        &remexec::ExecuteResponse {
          status: Some(bazel_protos::gen::google::rpc::Status {
            code: Code::DeadlineExceeded as i32,
            ..Default::default()
          }),
          ..Default::default()
        },
        "bazel_protos::gen::",
      )),
    ),
    ..Default::default()
  };

  match extract_execute_response(operation, Platform::Linux).await {
    Err(ExecutionError::Timeout) => (),
    other => assert!(false, "Want timeout error, got {:?}", other),
  };
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
    extract_execute_response(operation, Platform::Linux).await,
    Err(ExecutionError::MissingDigests(missing_files))
  );
}

#[tokio::test]
async fn extract_execute_response_missing_other_things() {
  let missing = vec![
    missing_preconditionfailure_violation(&TestData::roland().digest()),
    bazel_protos::gen::google::rpc::precondition_failure::Violation {
      r#type: "MISSING".to_owned(),
      subject: "monkeys".to_owned(),
      ..Default::default()
    },
  ];

  let operation = make_precondition_failure_operation(missing)
    .op
    .unwrap()
    .unwrap();

  match extract_execute_response(operation, Platform::Linux).await {
    Err(ExecutionError::Fatal(err)) => assert_contains(&err, "monkeys"),
    other => assert!(false, "Want fatal error, got {:?}", other),
  };
}

#[tokio::test]
async fn extract_execute_response_other_failed_precondition() {
  let missing = vec![
    bazel_protos::gen::google::rpc::precondition_failure::Violation {
      r#type: "OUT_OF_CAPACITY".to_owned(),
      ..Default::default()
    },
  ];

  let operation = make_precondition_failure_operation(missing)
    .op
    .unwrap()
    .unwrap();

  match extract_execute_response(operation, Platform::Linux).await {
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

  match extract_execute_response(operation, Platform::Linux).await {
    Err(ExecutionError::Fatal(err)) => assert_contains(&err.to_lowercase(), "precondition"),
    other => assert!(false, "Want fatal error, got {:?}", other),
  };
}

#[tokio::test]
async fn extract_execute_response_other_status() {
  let operation = Operation {
    name: "cat".to_owned(),
    done: true,
    result: Some(
      bazel_protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
        &remexec::ExecuteResponse {
          status: Some(bazel_protos::gen::google::rpc::Status {
            code: Code::PermissionDenied as i32,
            ..Default::default()
          }),
          ..Default::default()
        },
        "bazel_protos::gen::",
      )),
    ),
    ..Default::default()
  };

  match extract_execute_response(operation, Platform::Linux).await {
    Err(ExecutionError::Fatal(err)) => assert_contains(&err, "PermissionDenied"),
    other => assert!(false, "Want fatal error, got {:?}", other),
  };
}

#[tokio::test]
async fn remote_workunits_are_stored() {
  let mut workunit_store = WorkunitStore::setup_for_tests();
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
  let action_cache = mock::StubActionCache::new().unwrap();
  let (command_runner, _store) =
    create_command_runner(action_cache.address(), &cas, Platform::Linux);

  command_runner
    .extract_execute_response(OperationOrStatus::Operation(operation))
    .await
    .unwrap();

  let got_workunit_items: HashSet<(String, WorkunitState)> =
    workunit_store.with_latest_workunits(log::Level::Trace, |_, completed| {
      completed
        .iter()
        .map(|workunit| (workunit.name.clone(), workunit.state.clone()))
        .collect()
    });

  use concrete_time::Duration;
  use concrete_time::TimeSpan;

  let wanted_workunit_items = hashset! {
    (String::from("remote execution action scheduling"),
     WorkunitState::Completed {
      time_span: TimeSpan {
        start: Duration::new(0, 0),
        duration: Duration::new(1, 0),
      }
    },
    ),
    (String::from("remote execution worker input fetching"),
     WorkunitState::Completed {
        time_span: TimeSpan {
          start: Duration::new(2, 0),
          duration: Duration::new(1, 0),
        }
      }),
    (String::from("remote execution worker command executing"),
     WorkunitState::Completed {
        time_span: TimeSpan {
          start: Duration::new(4, 0),
          duration: Duration::new(1, 0),
        }
      }),
      (String::from("remote execution worker output uploading"),
      WorkunitState::Completed {
        time_span: TimeSpan {
          start: Duration::new(6, 0),
          duration: Duration::new(1, 0),
        }
      }),

  };

  assert!(got_workunit_items.is_superset(&wanted_workunit_items));
}

#[tokio::test]
async fn format_error_complete() {
  let error = bazel_protos::gen::google::rpc::Status {
    code: Code::Cancelled as i32,
    message: "Oops, oh well!".to_string(),
    ..Default::default()
  };

  assert_eq!(
    crate::remote::format_error(&error),
    "Cancelled: Oops, oh well!".to_string()
  );
}

#[tokio::test]
async fn extract_execute_response_unknown_code() {
  let error = bazel_protos::gen::google::rpc::Status {
    code: 555,
    message: "Oops, oh well!".to_string(),
    ..Default::default()
  };

  assert_eq!(
    crate::remote::format_error(&error),
    "555: Oops, oh well!".to_string()
  );
}

#[tokio::test]
async fn digest_command() {
  let command = remexec::Command {
    arguments: vec!["/bin/echo".to_string(), "foo".to_string()],
    environment_variables: vec![
      remexec::command::EnvironmentVariable {
        name: "A".to_string(),
        value: "a".to_string(),
      },
      remexec::command::EnvironmentVariable {
        name: "B".to_string(),
        value: "b".to_string(),
      },
    ],
    ..Default::default()
  };

  let digest = crate::remote::digest(&command).unwrap();

  assert_eq!(
    &digest.hash.to_hex(),
    "a32cd427e5df6a998199266681692989f56c19cabd1cc637bdd56ae2e62619b4"
  );
  assert_eq!(digest.size_bytes, 32)
}

#[tokio::test]
async fn extract_output_files_from_response_one_file() {
  let execute_response = remexec::ExecuteResponse {
    result: Some(remexec::ActionResult {
      exit_code: 0,
      output_files: vec![remexec::OutputFile {
        path: "roland".into(),
        digest: Some((&TestData::roland().digest()).into()),
        is_executable: false,
        ..Default::default()
      }],
      ..Default::default()
    }),
    ..Default::default()
  };

  assert_eq!(
    extract_output_files_from_response(&execute_response).await,
    Ok(TestDirectory::containing_roland().digest())
  )
}

#[tokio::test]
async fn extract_output_files_from_response_two_files_not_nested() {
  let execute_response = remexec::ExecuteResponse {
    result: Some(remexec::ActionResult {
      exit_code: 0,
      output_files: vec![
        remexec::OutputFile {
          path: "roland".into(),
          digest: Some((&TestData::roland().digest()).into()),
          is_executable: false,
          ..Default::default()
        },
        remexec::OutputFile {
          path: "treats".into(),
          digest: Some((&TestData::catnip().digest()).into()),
          is_executable: false,
          ..Default::default()
        },
      ],
      ..Default::default()
    }),
    ..Default::default()
  };

  assert_eq!(
    extract_output_files_from_response(&execute_response).await,
    Ok(TestDirectory::containing_roland_and_treats().digest())
  )
}

#[tokio::test]
async fn extract_output_files_from_response_two_files_nested() {
  let execute_response = remexec::ExecuteResponse {
    result: Some(remexec::ActionResult {
      exit_code: 0,
      output_files: vec![
        remexec::OutputFile {
          path: "cats/roland".into(),
          digest: Some((&TestData::roland().digest()).into()),
          is_executable: false,
          ..Default::default()
        },
        remexec::OutputFile {
          path: "treats".into(),
          digest: Some((&TestData::catnip().digest()).into()),
          is_executable: false,
          ..Default::default()
        },
      ],
      ..Default::default()
    }),
    ..Default::default()
  };

  assert_eq!(
    extract_output_files_from_response(&execute_response).await,
    Ok(TestDirectory::recursive().digest())
  )
}

#[tokio::test]
async fn extract_output_files_from_response_just_directory() {
  let test_tree: TestTree = TestDirectory::containing_roland().into();

  let execute_response = remexec::ExecuteResponse {
    result: Some(remexec::ActionResult {
      exit_code: 0,
      output_directories: vec![remexec::OutputDirectory {
        path: "cats".into(),
        tree_digest: Some(test_tree.digest().into()),
      }],
      ..Default::default()
    }),
    ..Default::default()
  };

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

  let execute_response = remexec::ExecuteResponse {
    result: Some(remexec::ActionResult {
      exit_code: 0,
      output_files: vec![remexec::OutputFile {
        path: "treats".into(),
        digest: Some((&TestData::catnip().digest()).into()),
        ..Default::default()
      }],
      output_directories: vec![
        remexec::OutputDirectory {
          path: "pets/cats".into(),
          tree_digest: Some((&TestTree::roland_at_root().digest()).into()),
        },
        remexec::OutputDirectory {
          path: "pets/dogs".into(),
          tree_digest: Some((&TestTree::robin_at_root().digest()).into()),
        },
      ],
      ..Default::default()
    }),
    ..Default::default()
  };

  assert_eq!(
    extract_output_files_from_response(&execute_response).await,
    Ok(Digest::new(
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
  let execute_response = remexec::ExecuteResponse {
    result: Some(remexec::ActionResult {
      exit_code: 0,
      output_directories: vec![remexec::OutputDirectory {
        path: String::new(),
        tree_digest: Some((&TestTree::roland_at_root().digest()).into()),
      }],
      ..Default::default()
    }),
    ..Default::default()
  };

  assert_eq!(
    extract_output_files_from_response(&execute_response).await,
    Ok(TestDirectory::containing_roland().digest())
  )
}

pub fn echo_foo_request() -> MultiPlatformProcess {
  let mut req = Process::new(owned_string_vec(&["/bin/echo", "-n", "foo"]));
  req.timeout = Some(Duration::from_millis(5000));
  req.description = "echo a foo".to_string();
  req.into()
}

pub(crate) fn make_incomplete_operation(operation_name: &str) -> MockOperation {
  let op = Operation {
    name: operation_name.to_string(),
    done: false,
    ..Default::default()
  };
  MockOperation::new(op)
}

pub(crate) fn make_retryable_operation_failure() -> MockOperation {
  let status = bazel_protos::gen::google::rpc::Status {
    code: Code::Aborted as i32,
    message: String::from("the bot running the task appears to be lost"),
    ..Default::default()
  };

  let operation = Operation {
    done: true,
    result: Some(
      bazel_protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
        &remexec::ExecuteResponse {
          status: Some(status),
          ..Default::default()
        },
        "bazel_protos::gen::",
      )),
    ),
    ..Default::default()
  };

  MockOperation {
    op: Ok(Some(operation)),
    duration: None,
  }
}

pub(crate) fn make_action_result(
  stdout: StdoutType,
  stderr: StderrType,
  exit_code: i32,
  metadata: Option<ExecutedActionMetadata>,
) -> remexec::ActionResult {
  let mut action_result = remexec::ActionResult::default();
  match stdout {
    StdoutType::Raw(stdout_raw) => {
      action_result.stdout_raw = stdout_raw.into_bytes().into();
    }
    StdoutType::Digest(stdout_digest) => {
      action_result.stdout_digest = Some((&stdout_digest).into());
    }
  }
  match stderr {
    StderrType::Raw(stderr_raw) => {
      action_result.stderr_raw = stderr_raw.into_bytes().into();
    }
    StderrType::Digest(stderr_digest) => {
      action_result.stderr_digest = Some((&stderr_digest).into());
    }
  }
  action_result.exit_code = exit_code;
  if let Some(metadata) = metadata {
    action_result.execution_metadata = Some(metadata);
  };
  action_result
}

fn make_successful_operation_with_maybe_metadata(
  operation_name: &str,
  stdout: StdoutType,
  stderr: StderrType,
  exit_code: i32,
  metadata: Option<ExecutedActionMetadata>,
) -> Operation {
  Operation {
    name: operation_name.to_string(),
    done: true,
    result: Some(
      bazel_protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
        &remexec::ExecuteResponse {
          status: Some(bazel_protos::gen::google::rpc::Status {
            code: Code::Ok as i32,
            ..Default::default()
          }),
          result: Some(make_action_result(stdout, stderr, exit_code, metadata)),
          ..Default::default()
        },
        "bazel_protos::gen::",
      )),
    ),
    ..Default::default()
  }
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
  let metadata = remexec::ExecutedActionMetadata {
    queued_timestamp: Some(timestamp_only_secs(0)),
    worker_start_timestamp: Some(timestamp_only_secs(1)),
    input_fetch_start_timestamp: Some(timestamp_only_secs(2)),
    input_fetch_completed_timestamp: Some(timestamp_only_secs(3)),
    execution_start_timestamp: Some(timestamp_only_secs(4)),
    execution_completed_timestamp: Some(timestamp_only_secs(5)),
    output_upload_start_timestamp: Some(timestamp_only_secs(6)),
    output_upload_completed_timestamp: Some(timestamp_only_secs(7)),
    worker_completed_timestamp: Some(timestamp_only_secs(8)),
    ..Default::default()
  };

  make_successful_operation_with_maybe_metadata(
    operation_name,
    stdout,
    stderr,
    exit_code,
    Some(metadata),
  )
}

fn timestamp_only_secs(v: i64) -> prost_types::Timestamp {
  prost_types::Timestamp {
    seconds: v,
    nanos: 0,
  }
}

pub(crate) fn make_precondition_failure_operation(
  violations: Vec<bazel_protos::gen::google::rpc::precondition_failure::Violation>,
) -> MockOperation {
  let operation = Operation {
    name: "cat".to_owned(),
    done: true,
    result: Some(
      bazel_protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
        &remexec::ExecuteResponse {
          status: Some(make_precondition_failure_status(violations)),
          ..Default::default()
        },
        "bazel_protos::gen::",
      )),
    ),
    ..Default::default()
  };
  MockOperation::new(operation)
}

fn make_precondition_failure_status(
  violations: Vec<bazel_protos::gen::google::rpc::precondition_failure::Violation>,
) -> bazel_protos::gen::google::rpc::Status {
  bazel_protos::gen::google::rpc::Status {
    code: Code::FailedPrecondition as i32,
    details: vec![make_any_proto(
      &bazel_protos::gen::google::rpc::PreconditionFailure { violations },
      "bazel_protos::gen::",
    )],
    ..Default::default()
  }
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

fn create_command_runner(
  address: String,
  cas: &mock::StubCAS,
  platform: Platform,
) -> (CommandRunner, Store) {
  let runtime = task_executor::Executor::new();
  let store_dir = TempDir::new().unwrap();
  let store = make_store(store_dir.path(), cas, runtime.clone());
  let command_runner = CommandRunner::new(
    &address,
    &address,
    ProcessMetadata::default(),
    None,
    BTreeMap::new(),
    store.clone(),
    platform,
    OVERALL_DEADLINE_SECS,
    RETRY_INTERVAL,
  )
  .expect("Failed to make command runner");
  (command_runner, store)
}

async fn run_command_remote(
  address: String,
  request: MultiPlatformProcess,
) -> Result<RemoteTestResult, String> {
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .tree(&TestTree::roland_at_root())
    .build();
  let (command_runner, store) = create_command_runner(address, &cas, Platform::Linux);
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

pub(crate) fn make_store(
  store_dir: &Path,
  cas: &mock::StubCAS,
  executor: task_executor::Executor,
) -> Store {
  Store::with_remote(
    executor,
    store_dir,
    &cas.address(),
    None,
    None,
    BTreeMap::new(),
    10 * 1024 * 1024,
    Duration::from_secs(1),
    1,
  )
  .expect("Failed to make store")
}

async fn extract_execute_response(
  operation: Operation,
  remote_platform: Platform,
) -> Result<RemoteTestResult, ExecutionError> {
  let action_cache = mock::StubActionCache::new().expect("failed to create action cache");

  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let (command_runner, store) =
    create_command_runner(action_cache.address(), &cas, remote_platform);

  let original = command_runner
    .extract_execute_response(OperationOrStatus::Operation(operation))
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
  execute_response: &remexec::ExecuteResponse,
) -> Result<Digest, String> {
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .tree(&TestTree::roland_at_root())
    .tree(&TestTree::robin_at_root())
    .build();
  let executor = task_executor::Executor::new();
  let store_dir = TempDir::new().unwrap();
  let store = make_store(store_dir.path(), &cas, executor.clone());
  let action_result = execute_response
    .result
    .as_ref()
    .ok_or_else(|| "No ActionResult found".to_string())?;
  crate::remote::extract_output_files(store, action_result, false).await
}

pub(crate) fn make_any_proto<T: Message>(message: &T, prefix: &str) -> prost_types::Any {
  let rust_type_name = type_name::<T>();
  let proto_type_name = rust_type_name
    .strip_prefix(prefix)
    .unwrap()
    .replace("::", ".");

  prost_types::Any {
    type_url: format!("type.googleapis.com/{}", proto_type_name),
    value: message.to_bytes().to_vec(),
  }
}

pub(crate) fn missing_preconditionfailure_violation(
  digest: &Digest,
) -> bazel_protos::gen::google::rpc::precondition_failure::Violation {
  {
    bazel_protos::gen::google::rpc::precondition_failure::Violation {
      r#type: "MISSING".to_owned(),
      subject: format!("blobs/{}/{}", digest.hash, digest.size_bytes),
      ..Default::default()
    }
  }
}

#[track_caller]
pub(crate) fn assert_contains(haystack: &str, needle: &str) {
  assert!(
    haystack.contains(needle),
    "{:?} should contain {:?}",
    haystack,
    needle
  )
}

pub(crate) fn cat_roland_request() -> MultiPlatformProcess {
  let argv = owned_string_vec(&["/bin/cat", "roland"]);
  let mut process = Process::new(argv);
  process.input_files = TestDirectory::containing_roland().digest();
  process.timeout = one_second();
  process.description = "cat a roland".to_string();
  process.into()
}

pub(crate) fn echo_roland_request() -> MultiPlatformProcess {
  let mut req = Process::new(owned_string_vec(&["/bin/echo", "meoooow"]));
  req.timeout = one_second();
  req.description = "unleash a roaring meow".to_string();
  req.into()
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
    .map(|req| req.name.clone())
    .collect::<Vec<_>>();
  assert_eq!(expected, cancels);
}

fn one_second() -> Option<Duration> {
  Some(Duration::from_millis(1000))
}
