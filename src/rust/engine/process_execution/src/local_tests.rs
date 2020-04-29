use tempfile;
use testutil;

use crate::{
  CommandRunner as CommandRunnerTrait, Context, FallibleProcessResultWithPlatform, Platform,
  PlatformConstraint, Process, RelativePath,
};
use futures::compat::Future01CompatExt;
use hashing::EMPTY_DIGEST;
use spectral::{assert_that, string::StrAssertions};
use std;
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::time::Duration;
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use testutil::path::find_bash;
use testutil::{as_bytes, owned_string_vec};
use tokio::runtime::Handle;

#[tokio::test]
#[cfg(unix)]
async fn stdout() {
  let result = run_command_locally(Process {
    argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "echo foo".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes("foo"),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
#[cfg(unix)]
async fn stdout_and_stderr_and_exit_code() {
  let result = run_command_locally(Process {
    argv: owned_string_vec(&["/bin/bash", "-c", "echo -n foo ; echo >&2 -n bar ; exit 1"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "echo foo and fail".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes("foo"),
      stderr: as_bytes("bar"),
      exit_code: 1,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
#[cfg(unix)]
async fn capture_exit_code_signal() {
  // Launch a process that kills itself with a signal.
  let result = run_command_locally(Process {
    argv: owned_string_vec(&["/bin/bash", "-c", "kill $$"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "kill self".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: -15,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
#[cfg(unix)]
async fn env() {
  let mut env: BTreeMap<String, String> = BTreeMap::new();
  env.insert("FOO".to_string(), "foo".to_string());
  env.insert("BAR".to_string(), "not foo".to_string());

  let result = run_command_locally(Process {
    argv: owned_string_vec(&["/usr/bin/env"]),
    env: env.clone(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "run env".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  let stdout = String::from_utf8(result.unwrap().stdout.to_vec()).unwrap();
  let got_env: BTreeMap<String, String> = stdout
    .split("\n")
    .filter(|line| !line.is_empty())
    .map(|line| line.splitn(2, "="))
    .map(|mut parts| {
      (
        parts.next().unwrap().to_string(),
        parts.next().unwrap_or("").to_string(),
      )
    })
    .filter(|x| x.0 != "PATH")
    .collect();

  assert_eq!(env, got_env);
}

#[tokio::test]
#[cfg(unix)]
async fn env_is_deterministic() {
  fn make_request() -> Process {
    let mut env = BTreeMap::new();
    env.insert("FOO".to_string(), "foo".to_string());
    env.insert("BAR".to_string(), "not foo".to_string());

    Process {
      argv: owned_string_vec(&["/usr/bin/env"]),
      env: env,
      working_directory: None,
      input_files: EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: one_second(),
      description: "run env".to_string(),
      unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
      jdk_home: None,
      target_platform: PlatformConstraint::None,
      is_nailgunnable: false,
    }
  }

  let result1 = run_command_locally(make_request()).await;
  let result2 = run_command_locally(make_request()).await;

  assert_eq!(result1.unwrap(), result2.unwrap());
}

#[tokio::test]
async fn binary_not_found() {
  run_command_locally(Process {
    argv: owned_string_vec(&["echo", "-n", "foo"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "echo foo".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await
  .expect_err("Want Err");
}

#[tokio::test]
async fn output_files_none() {
  let result = run_command_locally(Process {
    argv: owned_string_vec(&[&find_bash(), "-c", "exit 0"]),
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "bash".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;
  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
async fn output_files_one() {
  let result = run_command_locally(Process {
    argv: vec![
      find_bash(),
      "-c".to_owned(),
      format!("echo -n {} > {}", TestData::roland().string(), "roland"),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: vec![PathBuf::from("roland")].into_iter().collect(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "bash".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: TestDirectory::containing_roland().digest(),
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
async fn output_dirs() {
  let result = run_command_locally(Process {
    argv: vec![
      find_bash(),
      "-c".to_owned(),
      format!(
        "/bin/mkdir cats && echo -n {} > {} ; echo -n {} > treats",
        TestData::roland().string(),
        "cats/roland",
        TestData::catnip().string()
      ),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: vec![PathBuf::from("treats")].into_iter().collect(),
    output_directories: vec![PathBuf::from("cats")].into_iter().collect(),
    timeout: one_second(),
    description: "bash".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: TestDirectory::recursive().digest(),
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
async fn output_files_many() {
  let result = run_command_locally(Process {
    argv: vec![
      find_bash(),
      "-c".to_owned(),
      format!(
        "echo -n {} > cats/roland ; echo -n {} > treats",
        TestData::roland().string(),
        TestData::catnip().string()
      ),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: vec![PathBuf::from("cats/roland"), PathBuf::from("treats")]
      .into_iter()
      .collect(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "treats-roland".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: TestDirectory::recursive().digest(),
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
async fn output_files_execution_failure() {
  let result = run_command_locally(Process {
    argv: vec![
      find_bash(),
      "-c".to_owned(),
      format!(
        "echo -n {} > {} ; exit 1",
        TestData::roland().string(),
        "roland"
      ),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: vec![PathBuf::from("roland")].into_iter().collect(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "echo foo".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 1,
      output_directory: TestDirectory::containing_roland().digest(),
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
async fn output_files_partial_output() {
  let result = run_command_locally(Process {
    argv: vec![
      find_bash(),
      "-c".to_owned(),
      format!("echo -n {} > {}", TestData::roland().string(), "roland"),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: vec![PathBuf::from("roland"), PathBuf::from("susannah")]
      .into_iter()
      .collect(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "echo-roland".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: TestDirectory::containing_roland().digest(),
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
async fn output_overlapping_file_and_dir() {
  let result = run_command_locally(Process {
    argv: vec![
      find_bash(),
      "-c".to_owned(),
      format!("echo -n {} > cats/roland", TestData::roland().string()),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: vec![PathBuf::from("cats/roland")].into_iter().collect(),
    output_directories: vec![PathBuf::from("cats")].into_iter().collect(),
    timeout: one_second(),
    description: "bash".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: TestDirectory::nested().digest(),
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
async fn jdk_symlink() {
  let preserved_work_tmpdir = TempDir::new().unwrap();
  let roland = TestData::roland().bytes();
  std::fs::write(preserved_work_tmpdir.path().join("roland"), roland.clone())
    .expect("Writing temporary file");
  let result = run_command_locally(Process {
    argv: vec!["/bin/cat".to_owned(), ".jdk/roland".to_owned()],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: one_second(),
    description: "cat roland".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: Some(preserved_work_tmpdir.path().to_path_buf()),
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;
  assert_eq!(
    result,
    Ok(FallibleProcessResultWithPlatform {
      stdout: roland,
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    })
  )
}

#[tokio::test]
async fn test_directory_preservation() {
  let preserved_work_tmpdir = TempDir::new().unwrap();
  let preserved_work_root = preserved_work_tmpdir.path().to_owned();

  let result = run_command_locally_in_dir(
    Process {
      argv: vec![
        find_bash(),
        "-c".to_owned(),
        format!("echo -n {} > {}", TestData::roland().string(), "roland"),
      ],
      env: BTreeMap::new(),
      working_directory: None,
      input_files: EMPTY_DIGEST,
      output_files: vec![PathBuf::from("roland")].into_iter().collect(),
      output_directories: BTreeSet::new(),
      timeout: one_second(),
      description: "bash".to_string(),
      unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
      jdk_home: None,
      target_platform: PlatformConstraint::None,
      is_nailgunnable: false,
    },
    preserved_work_root.clone(),
    false,
    None,
    None,
  )
  .await;
  result.unwrap();

  assert!(preserved_work_root.exists());

  // Collect all of the top level sub-dirs under our test workdir.
  let subdirs = testutil::file::list_dir(&preserved_work_root);
  assert_eq!(subdirs.len(), 1);

  // Then look for a file like e.g. `/tmp/abc1234/process-execution7zt4pH/roland`
  let rolands_path = preserved_work_root.join(&subdirs[0]).join("roland");
  assert!(rolands_path.exists());
}

#[tokio::test]
async fn test_directory_preservation_error() {
  let preserved_work_tmpdir = TempDir::new().unwrap();
  let preserved_work_root = preserved_work_tmpdir.path().to_owned();

  assert!(preserved_work_root.exists());
  assert_eq!(testutil::file::list_dir(&preserved_work_root).len(), 0);

  run_command_locally_in_dir(
    Process {
      argv: vec!["doesnotexist".to_owned()],
      env: BTreeMap::new(),
      working_directory: None,
      input_files: EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: one_second(),
      description: "failing execution".to_string(),
      unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
      jdk_home: None,
      target_platform: PlatformConstraint::None,
      is_nailgunnable: false,
    },
    preserved_work_root.clone(),
    false,
    None,
    None,
  )
  .await
  .expect_err("Want process to fail");

  assert!(preserved_work_root.exists());
  // Collect all of the top level sub-dirs under our test workdir.
  assert_eq!(testutil::file::list_dir(&preserved_work_root).len(), 1);
}

#[tokio::test]
async fn all_containing_directories_for_outputs_are_created() {
  let result = run_command_locally(Process {
    argv: vec![
      find_bash(),
      "-c".to_owned(),
      format!(
        // mkdir would normally fail, since birds/ doesn't yet exist, as would echo, since cats/
        // does not exist, but we create the containing directories for all outputs before the
        // process executes.
        "/bin/mkdir birds/falcons && echo -n {} > cats/roland",
        TestData::roland().string()
      ),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: vec![PathBuf::from("cats/roland")].into_iter().collect(),
    output_directories: vec![PathBuf::from("birds/falcons")].into_iter().collect(),
    timeout: one_second(),
    description: "create nonoverlapping directories and file".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: TestDirectory::nested_dir_and_file().digest(),
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

#[tokio::test]
async fn output_empty_dir() {
  let result = run_command_locally(Process {
    argv: vec![
      find_bash(),
      "-c".to_owned(),
      "/bin/mkdir falcons".to_string(),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: vec![PathBuf::from("falcons")].into_iter().collect(),
    timeout: one_second(),
    description: "bash".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: TestDirectory::containing_falcons_dir().digest(),
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  )
}

/// This test attempts to make sure local only scratch files are materialized correctly by
/// making sure that with input_files being empty, we would be able to capture the content of
/// the local only scratch inputs as outputs.
#[tokio::test]
async fn local_only_scratch_files_materialized() {
  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new(Handle::current());
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

  // Prepare the store to contain roland, because the EPR needs to materialize it
  let roland_directory_digest = TestDirectory::containing_roland().digest();
  store
    .record_directory(&TestDirectory::containing_roland().directory(), true)
    .await
    .expect("Error saving directory");
  store
    .store_file_bytes(TestData::roland().bytes(), false)
    .await
    .expect("Error saving file bytes");

  let work_dir = TempDir::new().unwrap();
  let result = run_command_locally_in_dir(
    Process {
      argv: vec![find_bash(), "-c".to_owned(), format!("echo -n ''")],
      env: BTreeMap::new(),
      working_directory: None,
      input_files: EMPTY_DIGEST,
      output_files: vec![PathBuf::from("roland")].into_iter().collect(),
      output_directories: BTreeSet::new(),
      timeout: one_second(),
      description: "treats-roland".to_string(),
      unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
        roland_directory_digest,
      jdk_home: None,
      target_platform: PlatformConstraint::None,
      is_nailgunnable: false,
    },
    work_dir.path().to_owned(),
    true,
    Some(store),
    Some(executor),
  )
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes(""),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: roland_directory_digest,
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  );
}

#[tokio::test]
async fn timeout() {
  let result = run_command_locally(Process {
    argv: vec![
      find_bash(),
      "-c".to_owned(),
      "/bin/sleep 0.2; /bin/echo -n 'European Burmese'".to_string(),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Some(Duration::from_millis(100)),
    description: "sleepy-cat".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  })
  .await
  .unwrap();

  assert_eq!(result.exit_code, -15);
  let error_msg = String::from_utf8(result.stdout.to_vec()).unwrap();
  assert_that(&error_msg).contains("Exceeded timeout");
  assert_that(&error_msg).contains("sleepy-cat");
}

#[tokio::test]
async fn working_directory() {
  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new(Handle::current());
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

  // Prepare the store to contain /cats/roland, because the EPR needs to materialize it and then run
  // from the ./cats directory.
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
  let result = run_command_locally_in_dir(
    Process {
      argv: vec![find_bash(), "-c".to_owned(), "/bin/ls".to_string()],
      env: BTreeMap::new(),
      working_directory: Some(RelativePath::new("cats").unwrap()),
      input_files: TestDirectory::nested().digest(),
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: one_second(),
      description: "confused-cat".to_string(),
      unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
      jdk_home: None,
      target_platform: PlatformConstraint::None,
      is_nailgunnable: false,
    },
    work_dir.path().to_owned(),
    true,
    Some(store),
    Some(executor),
  )
  .await;

  assert_eq!(
    result.unwrap(),
    FallibleProcessResultWithPlatform {
      stdout: as_bytes("roland\n"),
      stderr: as_bytes(""),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
    }
  );
}

async fn run_command_locally(req: Process) -> Result<FallibleProcessResultWithPlatform, String> {
  let work_dir = TempDir::new().unwrap();
  run_command_locally_in_dir_with_cleanup(req, work_dir.path().to_owned()).await
}

async fn run_command_locally_in_dir_with_cleanup(
  req: Process,
  dir: PathBuf,
) -> Result<FallibleProcessResultWithPlatform, String> {
  run_command_locally_in_dir(req, dir, true, None, None).await
}

async fn run_command_locally_in_dir(
  req: Process,
  dir: PathBuf,
  cleanup: bool,
  store: Option<Store>,
  executor: Option<task_executor::Executor>,
) -> Result<FallibleProcessResultWithPlatform, String> {
  let store_dir = TempDir::new().unwrap();
  let executor = executor.unwrap_or_else(|| task_executor::Executor::new(Handle::current()));
  let store =
    store.unwrap_or_else(|| Store::local_only(executor.clone(), store_dir.path()).unwrap());
  let runner = crate::local::CommandRunner::new(store, executor.clone(), dir, cleanup);
  runner.run(req.into(), Context::default()).compat().await
}

fn one_second() -> Option<Duration> {
  Some(Duration::from_millis(1000))
}
