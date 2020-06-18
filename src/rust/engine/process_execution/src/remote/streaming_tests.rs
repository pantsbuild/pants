use std::collections::BTreeMap;
use std::convert::TryInto;
use std::time::Duration;

use bytes::Bytes;
use hashing::EMPTY_DIGEST;
use maplit::{btreemap, hashset};
use mock::execution_server::{ExpectedAPICall, MockOperation};
use protobuf::{Message, ProtobufEnum};
use spectral::assert_that;
use spectral::hashmap::HashMapAssertions;
use spectral::string::StrAssertions;
use spectral::vec::VecAssertions;
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use testutil::owned_string_vec;
use tokio::runtime::Handle;
use workunit_store::{Workunit, WorkunitMetadata, WorkunitState, WorkunitStore};

use crate::remote::{ExecutionError, OperationOrStatus, StreamingCommandRunner};
use crate::remote_tests::{
  assert_cancellation_requests, assert_contains, cat_roland_request, echo_foo_request,
  echo_roland_request, empty_request_metadata, make_any_proto, make_incomplete_operation,
  make_precondition_failure_operation, make_retryable_operation_failure, make_store,
  make_successful_operation, make_successful_operation_with_metadata,
  missing_preconditionfailure_violation, run_cmd_runner, workunits_with_constant_span_id,
  RemoteTestResult, StderrType, StdoutType,
};
use crate::{CommandRunner, Context, MultiPlatformProcess, Platform, Process};

const OVERALL_DEADLINE_SECS: Duration = Duration::from_secs(10 * 60);

fn create_command_runner(
  address: String,
  cas: &mock::StubCAS,
  platform: Platform,
) -> (StreamingCommandRunner, Store) {
  let runtime = task_executor::Executor::new(Handle::current());
  let store_dir = TempDir::new().unwrap();
  let store = make_store(store_dir.path(), cas, runtime.clone());
  let command_runner = StreamingCommandRunner::new(
    &address,
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store.clone(),
    platform,
    OVERALL_DEADLINE_SECS,
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

async fn extract_execute_response(
  operation: bazel_protos::operations::Operation,
  remote_platform: Platform,
) -> Result<RemoteTestResult, ExecutionError> {
  let cas = mock::StubCAS::builder()
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build();
  let (command_runner, store) = create_command_runner("".to_owned(), &cas, remote_platform);

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

#[tokio::test]
async fn successful_with_only_call_to_execute() {
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);
  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
        execute_request: crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        stream_responses: Ok(vec![
          make_incomplete_operation(&op_name),
          make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        ]),
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
async fn successful_after_reconnect_with_wait_execution() {
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);
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
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);
  let execute_request = echo_foo_request();
  let op_name_1 = "gimme-foo".to_string();
  let op_name_2 = "gimme-bar".to_string();

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
          stream_responses: Ok(vec![
            make_incomplete_operation(&op_name_1),
            make_retryable_operation_failure(),
          ]),
        },
        ExpectedAPICall::Execute {
          execute_request: crate::remote::make_execute_request(
            &execute_request.clone().try_into().unwrap(),
            empty_request_metadata(),
          )
          .unwrap()
          .2,
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
async fn server_rejecting_execute_request_gives_error() {
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

  let execute_request = echo_foo_request();

  let mock_server = mock::execution_server::TestServer::new(
    mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
      execute_request: crate::remote::make_execute_request(
        &Process::new(owned_string_vec(&["/bin/echo", "-n", "bar"])),
        empty_request_metadata(),
      )
      .unwrap()
      .2,
      stream_responses: Err(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::INVALID_ARGUMENT,
        None,
      )),
    }]),
    None,
  );

  let error = run_command_remote(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");
  assert_that(&error).contains("INVALID_ARGUMENT");
  assert_that(&error).contains("Did not expect this request");
}

#[tokio::test]
async fn server_sending_triggering_timeout_with_deadline_exceeded() {
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

  let execute_request = echo_foo_request();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
        execute_request: crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        stream_responses: Err(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::DEADLINE_EXCEEDED,
          None,
        )),
      }]),
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
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

  let execute_request = echo_foo_request();
  let op_name = "gimme-foo".to_string();

  let mock_server = {
    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
        execute_request: crate::remote::make_execute_request(
          &execute_request.clone().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        stream_responses: Ok(vec![
          make_incomplete_operation(&op_name),
          make_successful_operation(
            &op_name,
            StdoutType::Raw("foo".to_owned()),
            StderrType::Raw("".to_owned()),
            0,
          ),
        ]),
      }]),
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

  let command_runner = StreamingCommandRunner::new(
    &mock_server.address(),
    empty_request_metadata(),
    None,
    Some(String::from("catnip-will-get-you-anywhere")),
    btreemap! {
      String::from("cat") => String::from("roland"),
    },
    store,
    Platform::Linux,
    OVERALL_DEADLINE_SECS,
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
  assert_that!(message_headers).has_length(1);
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
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

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
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

  let runtime = task_executor::Executor::new(Handle::current());

  let test_stdout = TestData::roland();
  let test_stderr = TestData::catnip();

  let mock_server = {
    let op_name = "cat".to_owned();

    mock::execution_server::TestServer::new(
      mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
        execute_request: crate::remote::make_execute_request(
          &echo_roland_request().try_into().unwrap(),
          empty_request_metadata(),
        )
        .unwrap()
        .2,
        stream_responses: Ok(vec![
          make_incomplete_operation(&op_name),
          make_successful_operation(
            &op_name.clone(),
            StdoutType::Raw(test_stdout.string()),
            StderrType::Raw(test_stderr.string()),
            0,
          ),
        ]),
      }]),
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

  let cmd_runner = StreamingCommandRunner::new(
    &mock_server.address(),
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store.clone(),
    Platform::Linux,
    OVERALL_DEADLINE_SECS,
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
async fn bad_result_bytes() {
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

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
        stream_responses: Ok(vec![
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
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

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

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");

  assert_eq!(result, "INTERNAL: Something went wrong");
}

#[tokio::test]
async fn initial_response_missing_response_and_error() {
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

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

  let result = run_command_remote(mock_server.address(), execute_request)
    .await
    .expect_err("Want Err");

  assert_eq!(result, "Operation finished but no response supplied");
}

#[tokio::test]
async fn execute_missing_file_uploads_if_known() {
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

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
            empty_request_metadata(),
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
  let command_runner = StreamingCommandRunner::new(
    &mock_server.address(),
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store.clone(),
    Platform::Linux,
    OVERALL_DEADLINE_SECS,
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
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

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

  let runner = StreamingCommandRunner::new(
    &mock_server.address(),
    empty_request_metadata(),
    None,
    None,
    BTreeMap::new(),
    store,
    Platform::Linux,
    OVERALL_DEADLINE_SECS,
  )
  .unwrap();

  let error = runner
    .run(cat_roland_request(), Context::default())
    .await
    .expect_err("Want error");
  assert_contains(&error, &format!("{}", missing_digest.0));
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
  let mut operation = bazel_protos::operations::Operation::new();
  operation.set_name("cat".to_owned());
  operation.set_done(true);
  operation.set_response(make_any_proto(&{
    let mut response = bazel_protos::remote_execution::ExecuteResponse::new();
    let mut status = bazel_protos::status::Status::new();
    status.set_code(grpcio::RpcStatusCode::DEADLINE_EXCEEDED.into());
    response.set_status(status);
    response
  }));

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

  match extract_execute_response(operation, Platform::Linux).await {
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

  match extract_execute_response(operation, Platform::Linux).await {
    Err(ExecutionError::Fatal(err)) => assert_contains(&err, "PERMISSION_DENIED"),
    other => assert!(false, "Want fatal error, got {:?}", other),
  };
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
  let (command_runner, _store) = create_command_runner("".to_owned(), &cas, Platform::Linux);

  command_runner
    .extract_execute_response(OperationOrStatus::Operation(operation))
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
