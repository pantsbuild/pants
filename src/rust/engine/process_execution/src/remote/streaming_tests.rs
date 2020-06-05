use std::collections::BTreeMap;
use std::convert::TryInto;

use hashing::EMPTY_DIGEST;
use mock::execution_server::ExpectedAPICall;
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use tokio::runtime::Handle;

use crate::remote::StreamingCommandRunner;
use crate::remote_tests::{
  assert_cancellation_requests, echo_foo_request, empty_request_metadata,
  make_incomplete_operation, make_retryable_operation_failure, make_store,
  make_successful_operation, RemoteTestResult, StderrType, StdoutType,
};
use crate::CommandRunner;
use crate::{Context, MultiPlatformProcess, Platform};

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
