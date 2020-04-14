use crate::nailgun::{CommandRunner, ARGS_TO_START_NAILGUN, NAILGUN_MAIN_CLASS};
use crate::{PlatformConstraint, Process, ProcessMetadata};
use futures::compat::Future01CompatExt;
use hashing::EMPTY_DIGEST;
use std::fs::read_link;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
use store::Store;
use tempfile::TempDir;
use tokio::runtime::Handle;

fn mock_nailgun_runner(workdir_base: Option<PathBuf>) -> CommandRunner {
  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new(Handle::current());
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();
  let local_runner =
    crate::local::CommandRunner::new(store, executor.clone(), std::env::temp_dir(), true);
  let metadata = ProcessMetadata {
    instance_name: None,
    cache_key_gen_version: None,
    platform_properties: vec![],
  };
  let workdir_base = workdir_base.unwrap_or(std::env::temp_dir());

  CommandRunner::new(local_runner, metadata, workdir_base, executor.clone())
}

fn unique_temp_dir(base_dir: PathBuf, prefix: Option<String>) -> TempDir {
  tempfile::Builder::new()
    .prefix(&(prefix.unwrap_or("".to_string())))
    .tempdir_in(&base_dir)
    .expect("Error making tempdir for local process execution: {:?}")
}

fn mock_nailgunnable_request(jdk_home: Option<PathBuf>) -> Process {
  Process {
    argv: vec![],
    env: Default::default(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: Default::default(),
    output_directories: Default::default(),
    timeout: Default::default(),
    description: "".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: jdk_home,
    target_platform: PlatformConstraint::Darwin,
    is_nailgunnable: true,
  }
}

#[tokio::test]
async fn get_workdir_creates_directory_if_it_doesnt_exist() {
  let mock_workdir_base = unique_temp_dir(std::env::temp_dir(), None)
    .path()
    .to_owned();
  let mock_nailgun_name = "mock_non_existing_workdir".to_string();
  let runner = mock_nailgun_runner(Some(mock_workdir_base.clone()));

  let target_workdir = mock_workdir_base.join(mock_nailgun_name.clone());
  assert!(!target_workdir.exists());
  let res = runner.get_nailgun_workdir(&mock_nailgun_name);
  assert_eq!(res, Ok(target_workdir.clone()));
  assert!(target_workdir.exists());
}

#[tokio::test]
async fn get_workdir_returns_the_workdir_when_it_exists() {
  let mock_workdir_base = unique_temp_dir(std::env::temp_dir(), None)
    .path()
    .to_owned();
  let mock_nailgun_name = "mock_existing_workdir".to_string();
  let runner = mock_nailgun_runner(Some(mock_workdir_base.clone()));

  let target_workdir = mock_workdir_base.join(mock_nailgun_name.clone());
  assert!(!target_workdir.exists());
  let creation_res = fs::safe_create_dir_all(&target_workdir);
  assert!(creation_res.is_ok());
  assert!(target_workdir.exists());

  let res = runner.get_nailgun_workdir(&mock_nailgun_name);
  assert_eq!(res, Ok(target_workdir.clone()));
  assert!(target_workdir.exists());
}

#[tokio::test]
async fn creating_nailgun_server_request_updates_the_cli() {
  let req = super::construct_nailgun_server_request(
    &NAILGUN_MAIN_CLASS.to_string(),
    Vec::new(),
    PathBuf::from(""),
    PlatformConstraint::None,
  );
  assert_eq!(req.argv[0], NAILGUN_MAIN_CLASS);
  assert_eq!(req.argv[1..], ARGS_TO_START_NAILGUN);
}

#[tokio::test]
async fn creating_nailgun_client_request_removes_jdk_home() {
  let original_req = mock_nailgunnable_request(Some(PathBuf::from("some/path")));
  let req = super::construct_nailgun_client_request(original_req, "".to_string(), vec![]);
  assert_eq!(req.jdk_home, None);
}

#[tokio::test]
async fn nailgun_name_is_the_main_class() {
  let main_class = "my.main.class".to_string();
  let name = super::CommandRunner::calculate_nailgun_name(&main_class);
  assert_eq!(name, format!("nailgun_server_{}", main_class));
}

async fn materialize_with_jdk(
  runner: &CommandRunner,
  dir: PathBuf,
  jdk_path: PathBuf,
) -> Result<(), String> {
  let materializer = super::NailgunPool::materialize_workdir_for_server(
    runner.inner.store.clone(),
    dir,
    jdk_path,
    EMPTY_DIGEST,
  );
  materializer.compat().await
}

#[tokio::test]
async fn materializing_workdir_for_server_creates_a_link_for_the_jdk() {
  let workdir_base_tempdir = unique_temp_dir(std::env::temp_dir(), None);
  let workdir_base = workdir_base_tempdir.path().to_owned();
  let mock_jdk_dir = unique_temp_dir(std::env::temp_dir(), None);
  let mock_jdk_path = mock_jdk_dir.path().to_owned();
  let runner = mock_nailgun_runner(Some(workdir_base));
  let nailgun_name = "mock_server".to_string();

  let workdir_for_server = runner
    .get_nailgun_workdir(&nailgun_name)
    .expect("Error creating workdir for nailgun server");
  println!("Workdir for server {:?}", &workdir_for_server);

  // Assert that the materialization was successful
  let materialization_result =
    materialize_with_jdk(&runner, workdir_for_server.clone(), mock_jdk_path.clone()).await;
  assert_eq!(materialization_result, Ok(()));

  // Assert that the symlink points to the requested jdk
  let materialized_jdk_path = workdir_for_server.join(".jdk");
  let materialized_jdk = read_link(materialized_jdk_path);
  assert!(materialized_jdk.is_ok());
  assert_eq!(materialized_jdk.unwrap(), mock_jdk_path);
}

#[tokio::test]
async fn materializing_workdir_for_server_replaces_jdk_link_if_a_different_one_is_requested() {
  let workdir_base_tempdir = unique_temp_dir(std::env::temp_dir(), None);
  let workdir_base = workdir_base_tempdir.path().to_owned();

  let runner = mock_nailgun_runner(Some(workdir_base));
  let nailgun_name = "mock_server".to_string();

  let original_mock_jdk_dir = unique_temp_dir(std::env::temp_dir(), None);
  let original_mock_jdk_path = original_mock_jdk_dir.path().to_owned();
  let requested_mock_jdk_dir = unique_temp_dir(std::env::temp_dir(), None);
  let requested_mock_jdk_path = requested_mock_jdk_dir.path().to_owned();

  let workdir_for_server = runner
    .get_nailgun_workdir(&nailgun_name)
    .expect("Error creating workdir for nailgun server");
  let materialized_jdk_path = workdir_for_server.join(".jdk");

  // Manually create a symlink to one of the jdk files
  let symlink_res = symlink(original_mock_jdk_path, materialized_jdk_path.clone());
  assert!(symlink_res.is_ok());

  // Trigger materialization of the nailgun server workdir
  let materialization_result =
    materialize_with_jdk(&runner, workdir_for_server, requested_mock_jdk_path.clone()).await;
  assert!(materialization_result.is_ok());

  // Assert that the symlink points to the requested jdk, and not the original one
  let materialized_jdk = read_link(materialized_jdk_path);
  assert!(materialized_jdk.is_ok());
  assert_eq!(materialized_jdk.unwrap(), requested_mock_jdk_path);
}
