use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::path::PathBuf;
use std::time::Duration;

use bollard::image::CreateImageOptions;
use bollard::Docker;
use fs::{RelativePath, EMPTY_DIRECTORY_DIGEST};
use futures::StreamExt;
use maplit::hashset;
use spectral::assert_that;
use spectral::string::StrAssertions;
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use testutil::{owned_string_vec, relative_paths};
use workunit_store::{RunningWorkunit, WorkunitStore};

use super::docker::SANDBOX_PATH_IN_CONTAINER;
use crate::local::KeepSandboxes;
use crate::local_tests::named_caches_and_immutable_inputs;
use crate::{
  local, CacheName, CommandRunner, Context, FallibleProcessResultWithPlatform, InputDigests,
  Platform, Process, ProcessError,
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

macro_rules! setup_docker {
  () => {{
    let docker = match Docker::connect_with_local_defaults() {
      Ok(docker) => docker,
      Err(err) => {
        if cfg!(target_os = "macos") {
          println!("Skipping test due to Docker not being available: {:?}", err);
          return;
        } else {
          panic!("Docker should have been available for this test: {:?}", err);
        }
      }
    };

    let ping_response = docker.ping().await;
    if ping_response.is_err() {
      if cfg!(target_os = "macos") {
        println!(
          "Skipping test due to Docker not being available: {:?}",
          ping_response
        );
        return;
      } else {
        panic!(
          "Docker should have been available for this test: {:?}",
          ping_response
        );
      }
    }

    docker
  }};
}

#[tokio::test]
#[cfg(unix)]
async fn stdout() {
  let docker = setup_docker!();
  let result = run_command_via_docker(
    &docker,
    Process::new(owned_string_vec(&["/bin/echo", "-n", "foo"])),
  )
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
  let docker = setup_docker!();
  let result = run_command_via_docker(
    &docker,
    Process::new(owned_string_vec(&[
      SH_PATH,
      "-c",
      "echo -n foo ; echo >&2 -n bar ; exit 1",
    ])),
  )
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
  let docker = setup_docker!();

  // Launch a process that kills itself with a signal.
  let result = run_command_via_docker(
    &docker,
    Process::new(owned_string_vec(&[SH_PATH, "-c", "kill $$"])),
  )
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
#[ignore] // TODO(#16749): fix flaky test
#[cfg(unix)]
async fn env() {
  let docker = setup_docker!();

  let mut env: BTreeMap<String, String> = BTreeMap::new();
  env.insert("FOO".to_string(), "foo".to_string());
  env.insert("BAR".to_string(), "not foo".to_string());

  let result = run_command_via_docker(
    &docker,
    Process::new(owned_string_vec(&["/bin/env"])).env(env.clone()),
  )
  .await
  .unwrap();

  let exclude_keys = &["PATH", "HOME", "HOSTNAME"];
  let got_env = extract_env(result.stdout_bytes, exclude_keys).unwrap();
  assert_eq!(env, got_env);
}

#[tokio::test]
#[ignore] // TODO(#16749): fix flaky test
#[cfg(unix)]
async fn env_is_deterministic() {
  let docker = setup_docker!();

  fn make_request() -> Process {
    let mut env = BTreeMap::new();
    env.insert("FOO".to_string(), "foo".to_string());
    env.insert("BAR".to_string(), "not foo".to_string());
    Process::new(owned_string_vec(&["/bin/env"])).env(env)
  }

  let result1 = run_command_via_docker(&docker, make_request())
    .await
    .unwrap();
  let result2 = run_command_via_docker(&docker, make_request())
    .await
    .unwrap();

  let exclude_keys = &["PATH", "HOME", "HOSTNAME"];
  let env1 = extract_env(result1.stdout_bytes, exclude_keys).unwrap();
  let env2 = extract_env(result2.stdout_bytes, exclude_keys).unwrap();
  assert_eq!(env1, env2);
}

#[tokio::test]
async fn binary_not_found() {
  let docker = setup_docker!();

  // Use `xyzzy` as a command that should not exist.
  let result = run_command_via_docker(
    &docker,
    Process::new(owned_string_vec(&["xyzzy", "-n", "foo"])),
  )
  .await
  .unwrap();
  let stderr = String::from_utf8(result.stderr_bytes).unwrap();
  // Note: The error message is dependent on the fact that `tini` is used as the init process
  // in the container for the execution.
  assert!(stderr.contains("exec xyzzy failed: No such file or directory"));
}

#[tokio::test]
async fn output_files_none() {
  let docker = setup_docker!();

  let result = run_command_via_docker(
    &docker,
    Process::new(owned_string_vec(&[SH_PATH, "-c", "exit 0"])),
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, "".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
async fn output_files_one() {
  let docker = setup_docker!();

  let result = run_command_via_docker(
    &docker,
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
  let docker = setup_docker!();

  let result = run_command_via_docker(
    &docker,
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

#[tokio::test]
async fn output_files_many() {
  let docker = setup_docker!();

  let result = run_command_via_docker(
    &docker,
    Process::new(vec![
      SH_PATH.to_string(),
      "-c".to_owned(),
      format!(
        "echo -n {} > cats/roland.ext ; echo -n {} > treats.ext",
        TestData::roland().string(),
        TestData::catnip().string()
      ),
    ])
    .output_files(relative_paths(&["cats/roland.ext", "treats.ext"]).collect()),
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

#[tokio::test]
async fn output_files_execution_failure() {
  let docker = setup_docker!();

  let result = run_command_via_docker(
    &docker,
    Process::new(vec![
      SH_PATH.to_string(),
      "-c".to_owned(),
      format!(
        "echo -n {} > roland.ext ; exit 1",
        TestData::roland().string()
      ),
    ])
    .output_files(relative_paths(&["roland.ext"]).collect()),
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, "".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 1);
  assert_eq!(
    result.original.output_directory,
    TestDirectory::containing_roland().directory_digest()
  );
  assert_eq!(result.original.platform, Platform::current().unwrap());
}

#[tokio::test]
async fn output_files_partial_output() {
  let docker = setup_docker!();

  let result = run_command_via_docker(
    &docker,
    Process::new(vec![
      SH_PATH.to_string(),
      "-c".to_owned(),
      format!("echo -n {} > roland.ext", TestData::roland().string()),
    ])
    .output_files(
      relative_paths(&["roland.ext", "susannah"])
        .into_iter()
        .collect(),
    ),
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
async fn output_overlapping_file_and_dir() {
  let docker = setup_docker!();

  let result = run_command_via_docker(
    &docker,
    Process::new(vec![
      SH_PATH.to_string(),
      "-c".to_owned(),
      format!("echo -n {} > cats/roland.ext", TestData::roland().string()),
    ])
    .output_files(relative_paths(&["cats/roland.ext"]).collect())
    .output_directories(relative_paths(&["cats"]).collect()),
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, "".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(
    result.original.output_directory,
    TestDirectory::nested().directory_digest()
  );
  assert_eq!(result.original.platform, Platform::current().unwrap());
}

#[tokio::test]
async fn append_only_cache_created() {
  let docker = setup_docker!();

  let name = "geo";
  let dest_base = ".cache";
  let cache_name = CacheName::new(name.to_owned()).unwrap();
  let cache_dest = RelativePath::new(format!("{}/{}", dest_base, name)).unwrap();
  let result = run_command_via_docker(
    &docker,
    Process::new(owned_string_vec(&["/bin/ls", dest_base]))
      .append_only_caches(vec![(cache_name, cache_dest)].into_iter().collect()),
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, format!("{}\n", name).as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
  assert_eq!(result.original.platform, Platform::current().unwrap());
}

#[tokio::test]
#[cfg(unix)]
async fn test_apply_chroot() {
  let mut env: BTreeMap<String, String> = BTreeMap::new();
  env.insert("PATH".to_string(), "/usr/bin:{chroot}/bin".to_string());

  let work_dir = TempDir::new().unwrap();
  let mut req = Process::new(owned_string_vec(&["/usr/bin/env"])).env(env.clone());
  local::apply_chroot(work_dir.path().to_str().unwrap(), &mut req);

  let path = format!("/usr/bin:{}/bin", work_dir.path().to_str().unwrap());

  assert_eq!(&path, req.env.get(&"PATH".to_string()).unwrap());
}

#[tokio::test]
async fn test_chroot_placeholder() {
  let docker = setup_docker!();

  let (_, mut workunit) = WorkunitStore::setup_for_tests();
  let mut env: BTreeMap<String, String> = BTreeMap::new();
  env.insert("PATH".to_string(), "/usr/bin:{chroot}/bin".to_string());

  let work_tmpdir = TempDir::new().unwrap();
  let work_root = work_tmpdir.path().to_owned();

  let result = run_command_via_docker_in_dir(
    &docker,
    Process::new(vec!["/bin/env".to_owned()]).env(env.clone()),
    work_root.clone(),
    KeepSandboxes::Always,
    &mut workunit,
    None,
    None,
  )
  .await
  .unwrap();

  let got_env = extract_env(result.stdout_bytes, &[]).unwrap();
  let actual_path = got_env.get("PATH").unwrap();
  assert_eq!(
    *actual_path,
    format!("/usr/bin:{}/bin", SANDBOX_PATH_IN_CONTAINER)
  );
}

#[tokio::test]
async fn all_containing_directories_for_outputs_are_created() {
  let docker = setup_docker!();

  let result = run_command_via_docker(
    &docker,
    Process::new(vec![
      SH_PATH.to_string(),
      "-c".to_owned(),
      format!(
        // mkdir would normally fail, since birds/ doesn't yet exist, as would echo, since cats/
        // does not exist, but we create the containing directories for all outputs before the
        // process executes.
        "/bin/mkdir birds/falcons && echo -n {} > cats/roland.ext",
        TestData::roland().string()
      ),
    ])
    .output_files(relative_paths(&["cats/roland.ext"]).collect())
    .output_directories(relative_paths(&["birds/falcons"]).collect()),
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, "".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(
    result.original.output_directory,
    TestDirectory::nested_dir_and_file().directory_digest()
  );
  assert_eq!(result.original.platform, Platform::current().unwrap());
}

#[tokio::test]
async fn output_empty_dir() {
  let docker = setup_docker!();

  let result = run_command_via_docker(
    &docker,
    Process::new(vec![
      SH_PATH.to_string(),
      "-c".to_owned(),
      "/bin/mkdir falcons".to_string(),
    ])
    .output_directories(relative_paths(&["falcons"]).collect()),
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, "".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(
    result.original.output_directory,
    TestDirectory::containing_falcons_dir().directory_digest()
  );
  assert_eq!(result.original.platform, Platform::current().unwrap());
}

#[tokio::test]
async fn timeout() {
  let docker = setup_docker!();

  let argv = vec![
    SH_PATH.to_string(),
    "-c".to_owned(),
    "/bin/sleep 0.2; /bin/echo -n 'European Burmese'".to_string(),
  ];

  let mut process = Process::new(argv);
  process.timeout = Some(Duration::from_millis(100));
  process.description = "sleepy-cat".to_string();

  let result = run_command_via_docker(&docker, process).await.unwrap();

  assert_eq!(result.original.exit_code, -15);
  let error_msg = String::from_utf8(result.stdout_bytes.to_vec()).unwrap();
  assert_that(&error_msg).contains("Exceeded timeout");
  assert_that(&error_msg).contains("sleepy-cat");
}

#[tokio::test]
async fn working_directory() {
  let docker = setup_docker!();
  let (_, mut workunit) = WorkunitStore::setup_for_tests();

  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new();
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

  // Prepare the store to contain /cats/roland.ext, because the EPR needs to materialize it and
  // then run from the ./cats directory.
  store
    .store_file_bytes(TestData::roland().bytes(), false)
    .await
    .expect("Error saving file bytes");
  store
    .record_directory(&TestDirectory::containing_roland().directory(), true)
    .await
    .expect("Error saving directory");
  store
    .record_directory(&TestDirectory::nested().directory(), true)
    .await
    .expect("Error saving directory");

  let work_dir = TempDir::new().unwrap();

  let mut process = Process::new(vec![
    SH_PATH.to_string(),
    "-c".to_owned(),
    "/bin/ls".to_string(),
  ]);
  process.working_directory = Some(RelativePath::new("cats").unwrap());
  process.output_directories = relative_paths(&["roland.ext"]).collect::<BTreeSet<_>>();
  process.input_digests =
    InputDigests::with_input_files(TestDirectory::nested().directory_digest());
  process.timeout = Some(Duration::from_secs(1));
  process.description = "confused-cat".to_string();

  let result = run_command_via_docker_in_dir(
    &docker,
    process,
    work_dir.path().to_owned(),
    KeepSandboxes::Never,
    &mut workunit,
    Some(store),
    Some(executor),
  )
  .await
  .unwrap();

  assert_eq!(result.stdout_bytes, "roland.ext\n".as_bytes());
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
  assert_eq!(
    result.original.output_directory,
    TestDirectory::containing_roland().directory_digest()
  );
  assert_eq!(result.original.platform, Platform::current().unwrap());
}

#[tokio::test]
async fn immutable_inputs() {
  let docker = setup_docker!();
  let (_, mut workunit) = WorkunitStore::setup_for_tests();

  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new();
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

  store
    .store_file_bytes(TestData::roland().bytes(), false)
    .await
    .expect("Error saving file bytes");
  store
    .record_directory(&TestDirectory::containing_roland().directory(), true)
    .await
    .expect("Error saving directory");
  store
    .record_directory(&TestDirectory::containing_falcons_dir().directory(), true)
    .await
    .expect("Error saving directory");

  let work_dir = TempDir::new().unwrap();

  let mut process = Process::new(vec![
    SH_PATH.to_string(),
    "-c".to_owned(),
    "/bin/ls".to_string(),
  ]);
  process.input_digests = InputDigests::new(
    &store,
    TestDirectory::containing_falcons_dir().directory_digest(),
    {
      let mut map = BTreeMap::new();
      map.insert(
        RelativePath::new("cats").unwrap(),
        TestDirectory::containing_roland().directory_digest(),
      );
      map
    },
    BTreeSet::default(),
  )
  .await
  .unwrap();
  process.timeout = Some(Duration::from_secs(1));
  process.description = "confused-cat".to_string();
  process.docker_image = Some(IMAGE.to_string());

  let result = run_command_via_docker_in_dir(
    &docker,
    process,
    work_dir.path().to_owned(),
    KeepSandboxes::Never,
    &mut workunit,
    Some(store),
    Some(executor),
  )
  .await
  .unwrap();

  let stdout_lines = std::str::from_utf8(&result.stdout_bytes)
    .unwrap()
    .lines()
    .collect::<HashSet<_>>();
  assert_eq!(stdout_lines, hashset! {"falcons", "cats"});
  assert_eq!(result.stderr_bytes, "".as_bytes());
  assert_eq!(result.original.exit_code, 0);
}

// DOCKER-TODO: We should debounce calls to this method from multiple tests in the same process.
async fn pull_image(docker: &Docker, image: &str) {
  let create_image_options = CreateImageOptions::<String> {
    from_image: image.to_string(),
    ..CreateImageOptions::default()
  };
  let mut result_stream = docker.create_image(Some(create_image_options), None, None);
  while let Some(msg) = result_stream.next().await {
    if msg.is_err() {
      panic!("Unable to pull image `{}` for test: {:?}", image, msg);
    }
  }
}

async fn run_command_via_docker_in_dir(
  docker: &Docker,
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
  pull_image(docker, IMAGE).await;
  let runner = crate::docker::CommandRunner::new(
    store.clone(),
    executor.clone(),
    dir.clone(),
    named_caches,
    immutable_inputs,
    cleanup,
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

async fn run_command_via_docker(
  docker: &Docker,
  req: Process,
) -> Result<LocalTestResult, ProcessError> {
  let (_, mut workunit) = WorkunitStore::setup_for_tests();
  let work_dir = TempDir::new().unwrap();
  let work_dir_path = work_dir.path().to_owned();
  run_command_via_docker_in_dir(
    docker,
    req,
    work_dir_path,
    KeepSandboxes::Never,
    &mut workunit,
    None,
    None,
  )
  .await
}
