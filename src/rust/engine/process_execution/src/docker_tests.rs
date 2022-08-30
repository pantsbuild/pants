use std::collections::BTreeMap;
use std::path::PathBuf;

use bollard::image::CreateImageOptions;
use bollard::Docker;
use fs::EMPTY_DIRECTORY_DIGEST;
use futures::StreamExt;
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use testutil::{owned_string_vec, relative_paths};
use workunit_store::{RunningWorkunit, WorkunitStore};

use crate::local::KeepSandboxes;
use crate::local_tests::named_caches_and_immutable_inputs;
use crate::{
  CommandRunner, Context, FallibleProcessResultWithPlatform, Platform, Process, ProcessError,
};

/// Docker image to use for most tests in this file.
const IMAGE: &'static str = "busybox:1.34.1";

/// Path to `sh` within the image.
const SH_PATH: &'static str = "/bin/sh";

#[derive(PartialEq, Debug)]
struct LocalTestResult {
  original: FallibleProcessResultWithPlatform,
  stdout_bytes: Vec<u8>,
  stderr_bytes: Vec<u8>,
}

#[tokio::test]
#[cfg(unix)]
async fn stdout() {
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
    SH_PATH,
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

#[tokio::test]
#[cfg(unix)]
async fn capture_exit_code_signal() {
  // Launch a process that kills itself with a signal.
  let result = run_command_via_docker(Process::new(owned_string_vec(&[SH_PATH, "-c", "kill $$"])))
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  // DOCKER-TODO: Figure out a way to capture the signal from the container. Docker does not
  // seem to make that available. The `143` code comes from the init process in the container.
  // assert_eq!(result.original.exit_code, -15);
  assert_eq!(result.original.exit_code, 143);
  assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
  assert_eq!(result.original.platform, Platform::current().unwrap());
}

fn extract_env(
  content: Vec<u8>,
  exclude_keys: &[&str],
) -> Result<BTreeMap<String, String>, String> {
  let content =
    String::from_utf8(content).map_err(|_| "Invalid UTF-8 in env output".to_string())?;
  let result = content
    .split("\n")
    .filter(|line| !line.is_empty())
    .map(|line| line.splitn(2, "="))
    .map(|mut parts| {
      (
        parts.next().unwrap().to_string(),
        parts.next().unwrap_or("").to_string(),
      )
    })
    .filter(|x| !exclude_keys.iter().any(|&k| k == x.0))
    .collect();
  Ok(result)
}

#[tokio::test]
#[cfg(unix)]
async fn env() {
  let mut env: BTreeMap<String, String> = BTreeMap::new();
  env.insert("FOO".to_string(), "foo".to_string());
  env.insert("BAR".to_string(), "not foo".to_string());

  let result =
    run_command_via_docker(Process::new(owned_string_vec(&["/bin/env"])).env(env.clone()))
      .await
      .unwrap();

  let exclude_keys = &["PATH", "HOME", "HOSTNAME"];
  let got_env = extract_env(result.stdout_bytes, exclude_keys).unwrap();
  assert_eq!(env, got_env);
}

#[tokio::test]
#[cfg(unix)]
async fn env_is_deterministic() {
  fn make_request() -> Process {
    let mut env = BTreeMap::new();
    env.insert("FOO".to_string(), "foo".to_string());
    env.insert("BAR".to_string(), "not foo".to_string());
    Process::new(owned_string_vec(&["/bin/env"])).env(env)
  }

  let result1 = run_command_via_docker(make_request()).await.unwrap();
  let result2 = run_command_via_docker(make_request()).await.unwrap();

  let exclude_keys = &["PATH", "HOME", "HOSTNAME"];
  let env1 = extract_env(result1.stdout_bytes, exclude_keys).unwrap();
  let env2 = extract_env(result2.stdout_bytes, exclude_keys).unwrap();
  assert_eq!(env1, env2);
}

#[tokio::test]
async fn binary_not_found() {
  // Use `xyzzy` as a command that should not exist.
  let result = run_command_via_docker(Process::new(owned_string_vec(&["xyzzy", "-n", "foo"])))
    .await
    .unwrap();
  let stderr = String::from_utf8(result.stderr_bytes).unwrap();
  // Note: The error message is dependent on the fact that `tini` is used as the init process
  // in the container for the execution.
  assert!(stderr.contains("exec xyzzy failed: No such file or directory"));
}

#[tokio::test]
async fn output_files_none() {
  let result = run_command_via_docker(Process::new(owned_string_vec(&[SH_PATH, "-c", "exit 0"])))
    .await
    .unwrap();

  assert_eq!(result.stdout_bytes, "".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
async fn output_files_one() {
  let result = run_command_via_docker(
    Process::new(vec![
      SH_PATH.to_string(),
      "-c".to_owned(),
      format!("echo -n {} > roland.ext", TestData::roland().string()),
    ])
    .output_files(relative_paths(&["roland.ext"]).collect()),
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, "".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(
    result.original.output_directory,
    TestDirectory::containing_roland().directory_digest()
  );
  assert_eq!(result.original.platform, Platform::current().unwrap());
}

#[tokio::test]
async fn output_dirs() {
  let result = run_command_via_docker(
    Process::new(vec![
      SH_PATH.to_string(),
      "-c".to_owned(),
      format!(
        "/bin/mkdir cats && echo -n {} > cats/roland.ext ; echo -n {} > treats.ext",
        TestData::roland().string(),
        TestData::catnip().string()
      ),
    ])
    .output_files(relative_paths(&["treats.ext"]).collect())
    .output_directories(relative_paths(&["cats"]).collect()),
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, "".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(
    result.original.output_directory,
    TestDirectory::recursive().directory_digest()
  );
  assert_eq!(result.original.platform, Platform::current().unwrap());
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
