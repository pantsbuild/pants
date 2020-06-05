use std::collections::BTreeMap;
use std::convert::TryInto;

use hashing::EMPTY_DIGEST;
use maplit::btreemap;
use mock::execution_server::ExpectedAPICall;
use protobuf::Message;
use spectral::assert_that;
use spectral::hashmap::HashMapAssertions;
use spectral::string::StrAssertions;
use spectral::vec::VecAssertions;
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use testutil::owned_string_vec;
use tokio::runtime::Handle;

use crate::remote::{ExecutionError, OperationOrStatus, StreamingCommandRunner};
use crate::remote_tests::{
  assert_cancellation_requests, echo_foo_request, empty_request_metadata,
  make_incomplete_operation, make_retryable_operation_failure, make_store,
  make_successful_operation, RemoteTestResult, StderrType, StdoutType,
};
use crate::{CommandRunner, Context, MultiPlatformProcess, Platform, Process};
use std::time::Duration;
use workunit_store::WorkunitStore;

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
async fn sends_headers() {
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
