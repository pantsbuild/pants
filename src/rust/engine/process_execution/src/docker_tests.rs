use bollard::image::CreateImageOptions;
use bollard::Docker;
use std::path::PathBuf;

use fs::EMPTY_DIRECTORY_DIGEST;
use futures::StreamExt;
use store::Store;
use tempfile::TempDir;
use testutil::owned_string_vec;
use workunit_store::{RunningWorkunit, WorkunitStore};

use crate::local::KeepSandboxes;
use crate::local_tests::named_caches_and_immutable_inputs;
use crate::{CommandRunner, Context, FallibleProcessResultWithPlatform, Process, ProcessError};

/// Docker image to use for most tests in this file.
const IMAGE: &'static str = "python:3.9.13";

#[derive(PartialEq, Debug)]
struct LocalTestResult {
  original: FallibleProcessResultWithPlatform,
  stdout_bytes: Vec<u8>,
  stderr_bytes: Vec<u8>,
}

#[tokio::test]
#[cfg(unix)]
async fn stdout() {
  let _ = env_logger::try_init();
  let result = run_command_via_docker(Process::new(owned_string_vec(&["/bin/echo", "-n", "foo"])))
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
#[cfg(unix)]
async fn stdout_and_stderr_and_exit_code() {
  let _ = env_logger::try_init();
  let result = run_command_via_docker(Process::new(owned_string_vec(&[
    "/bin/bash",
    "-c",
    "echo -n foo ; echo >&2 -n bar ; exit 1",
  ])))
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, "foo".as_bytes());
  assert_eq!(result.stderr_bytes, "bar".as_bytes());
  assert_eq!(result.original.exit_code, 1);
  assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

// DOCKER-TODO: We should debounce calls to this method from multiple tests in the same process.
async fn pull_docker_image(image: &str) {
  let docker =
    Docker::connect_with_local_defaults().expect("Initialize Docker connection for image pull");
  let create_image_options = CreateImageOptions::<String> {
    from_image: image.to_string(),
    ..CreateImageOptions::default()
  };
  let mut result_stream = docker.create_image(Some(create_image_options), None, None);
  while let Some(msg) = result_stream.next().await {
    if msg.is_err() {
      panic!("Unable to pull image `{}` for test: {:?}", IMAGE, msg);
    }
  }
}

async fn run_command_via_docker_in_dir(
  req: Process,
  dir: PathBuf,
  cleanup: KeepSandboxes,
  workunit: &mut RunningWorkunit,
  store: Option<Store>,
  executor: Option<task_executor::Executor>,
) -> Result<LocalTestResult, ProcessError> {
  let store_dir = TempDir::new().unwrap();
  let executor = executor.unwrap_or_else(|| task_executor::Executor::new());
  let store =
    store.unwrap_or_else(|| Store::local_only(executor.clone(), store_dir.path()).unwrap());
  let (_caches_dir, named_caches, immutable_inputs) =
    named_caches_and_immutable_inputs(store.clone());
  pull_docker_image(IMAGE).await;
  let runner = crate::docker::CommandRunner::new(
    store.clone(),
    executor.clone(),
    dir.clone(),
    named_caches,
    immutable_inputs,
    cleanup,
    IMAGE.to_string(),
  )?;
  let original = runner.run(Context::default(), workunit, req.into()).await?;
  let stdout_bytes = store
    .load_file_bytes_with(original.stdout_digest, |bytes| bytes.to_vec())
    .await?;
  let stderr_bytes = store
    .load_file_bytes_with(original.stderr_digest, |bytes| bytes.to_vec())
    .await?;
  Ok(LocalTestResult {
    original,
    stdout_bytes,
    stderr_bytes,
  })
}

async fn run_command_via_docker(req: Process) -> Result<LocalTestResult, ProcessError> {
  let (_, mut workunit) = WorkunitStore::setup_for_tests();
  let work_dir = TempDir::new().unwrap();
  let work_dir_path = work_dir.path().to_owned();
  run_command_via_docker_in_dir(
    req,
    work_dir_path,
    KeepSandboxes::Never,
    &mut workunit,
    None,
    None,
  )
  .await
}
