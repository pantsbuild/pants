extern crate tempdir;

use boxfuture::{BoxFuture, Boxable};
use fs::{self, PathStatGetter};
use futures::{future, Future};
use std::process::Command;
use std::sync::Arc;

use tokio_process::CommandExt;

use super::{ExecuteProcessRequest, ExecuteProcessResult};

use bytes::Bytes;

pub struct CommandRunner {
  store: fs::Store,
  fs_pool: Arc<fs::ResettablePool>,
}

impl CommandRunner {
  pub fn new(store: fs::Store, fs_pool: Arc<fs::ResettablePool>) -> CommandRunner {
    CommandRunner { store, fs_pool }
  }
}

impl super::CommandRunner for CommandRunner {
  ///
  /// Runs a command on this machine in the passed working directory.
  ///
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<ExecuteProcessResult, String> {
    let workdir = try_future!(
      tempdir::TempDir::new("process-execution").map_err(|err| format!(
        "Error making tempdir for local process execution: {:?}",
        err
      ))
    );

    let store = self.store.clone();
    let fs_pool = self.fs_pool.clone();
    let env = req.env;
    let output_file_paths = req.output_files;
    let argv = req.argv;
    self
      .store
      .materialize_directory(workdir.path().to_owned(), req.input_files)
      .and_then(move |()| {
        Command::new(&argv[0])
                  .args(&argv[1..])
                  .current_dir(workdir.path())
                  .env_clear()
                  // It would be really nice not to have to manually set PATH but this is sadly the only way
                  // to stop automatic PATH searching.
                  .env("PATH", "")
                  .envs(env)
                  .output_async()
                  .map_err(|e| format!("Error executing process: {:?}", e))
                  .map(|output| (output, workdir))
      })
      .and_then(|(output, workdir)| {
        let output_snapshot = if output_file_paths.is_empty() {
          future::ok(fs::Snapshot::empty()).to_boxed()
        } else {
          // Use no ignore patterns, because we are looking for explicitly listed paths.
          future::done(fs::PosixFS::new(
                  workdir.path(),
                  fs_pool,
                  vec![],
              )).map_err(|err| {
                  format!(
                      "Error making posix_fs to fetch local process execution output files: {}",
                      err
                  )
              })
                  .map(|posix_fs| Arc::new(posix_fs))
                  .and_then(|posix_fs| {
                      posix_fs
                          .path_stats(output_file_paths.into_iter().collect())
                          .map_err(|e| format!("Error stating output files: {}", e))
                          .and_then(move |paths| {
                              fs::Snapshot::from_path_stats(
                                  store.clone(),
                                  fs::OneOffStoreFileByDigest::new(store, posix_fs),
                                  paths.into_iter().filter_map(|v| v).collect(),
                              )
                          })
                  })
                  // Force workdir not to get dropped until after we've ingested the outputs
                  .map(|result| (result, workdir))
                  .map(|(result, _workdir)| result)
                  .to_boxed()
        };

        output_snapshot
          .map(|snapshot| ExecuteProcessResult {
            stdout: Bytes::from(output.stdout),
            stderr: Bytes::from(output.stderr),
            exit_code: output.status.code().unwrap(),
            output_directory: snapshot.digest,
          })
          .to_boxed()
      })
      .to_boxed()
  }

  fn reset_prefork(&self) {
    self.store.reset_prefork();
    self.fs_pool.reset();
  }
}

#[cfg(test)]
mod tests {
  extern crate tempdir;
  extern crate testutil;

  use fs;
  use futures::Future;
  use super::{ExecuteProcessRequest, ExecuteProcessResult};
  use super::super::CommandRunner as CommandRunnerTrait;
  use std;
  use std::collections::{BTreeMap, BTreeSet};
  use std::env;
  use std::os::unix::fs::PermissionsExt;
  use std::path::{Path, PathBuf};
  use std::sync::Arc;
  use tempdir::TempDir;
  use self::testutil::{as_bytes, owned_string_vec};
  use testutil::data::{TestData, TestDirectory};

  #[test]
  #[cfg(unix)]
  fn stdout() {
    let result = run_command_locally(ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
    });

    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
      }
    )
  }

  #[test]
  #[cfg(unix)]
  fn stdout_and_stderr_and_exit_code() {
    let result = run_command_locally(ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/bash", "-c", "echo -n foo ; echo >&2 -n bar ; exit 1"]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
    });

    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes("bar"),
        exit_code: 1,
        output_directory: fs::EMPTY_DIGEST,
      }
    )
  }

  #[test]
  #[cfg(unix)]
  fn env() {
    let mut env: BTreeMap<String, String> = BTreeMap::new();
    env.insert("FOO".to_string(), "foo".to_string());
    env.insert("BAR".to_string(), "not foo".to_string());

    let result = run_command_locally(ExecuteProcessRequest {
      argv: owned_string_vec(&["/usr/bin/env"]),
      env: env.clone(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
    });

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

  #[test]
  #[cfg(unix)]
  fn env_is_deterministic() {
    fn make_request() -> ExecuteProcessRequest {
      let mut env = BTreeMap::new();
      env.insert("FOO".to_string(), "foo".to_string());
      env.insert("BAR".to_string(), "not foo".to_string());

      ExecuteProcessRequest {
        argv: owned_string_vec(&["/usr/bin/env"]),
        env: env,
        input_files: fs::EMPTY_DIGEST,
        output_files: BTreeSet::new(),
      }
    }

    let result1 = run_command_locally(make_request());
    let result2 = run_command_locally(make_request());

    assert_eq!(result1.unwrap(), result2.unwrap());
  }

  #[test]
  fn binary_not_found() {
    run_command_locally(ExecuteProcessRequest {
      argv: owned_string_vec(&["echo", "-n", "foo"]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
    }).expect_err("Want Err");
  }

  #[test]
  fn output_files_none() {
    let result = run_command_locally(ExecuteProcessRequest {
      argv: owned_string_vec(&[
        which("bash").expect("No bash on PATH").to_str().unwrap(),
        "-c",
        "exit 0",
      ]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
    });
    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
      }
    )
  }

  #[test]
  fn output_files_one() {
    let result = run_command_locally_in_dir(ExecuteProcessRequest {
      argv: vec![
        find_bash(),
        "-c".to_owned(),
        format!("echo -n {} > {}", TestData::roland().string(), "roland"),
      ],
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: vec![PathBuf::from("roland")].into_iter().collect(),
    });

    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::containing_roland().digest(),
      }
    )
  }

  #[test]
  fn output_files_many() {
    let result = run_command_locally_in_dir(ExecuteProcessRequest {
      argv: vec![
        find_bash(),
        "-c".to_owned(),
        format!(
          "/bin/mkdir cats ; echo -n {} > cats/roland ; echo -n {} > treats",
          TestData::roland().string(),
          TestData::catnip().string()
        ),
      ],
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: vec![PathBuf::from("cats/roland"), PathBuf::from("treats")]
        .into_iter()
        .collect(),
    });

    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::recursive().digest(),
      }
    )
  }

  #[test]
  fn output_files_execution_failure() {
    let result = run_command_locally_in_dir(ExecuteProcessRequest {
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
      input_files: fs::EMPTY_DIGEST,
      output_files: vec![PathBuf::from("roland")].into_iter().collect(),
    });

    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 1,
        output_directory: TestDirectory::containing_roland().digest(),
      }
    )
  }

  #[test]
  fn output_files_partial_output() {
    let result = run_command_locally_in_dir(ExecuteProcessRequest {
      argv: vec![
        find_bash(),
        "-c".to_owned(),
        format!("echo -n {} > {}", TestData::roland().string(), "roland"),
      ],
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: vec![PathBuf::from("roland"), PathBuf::from("susannah")]
        .into_iter()
        .collect(),
    });

    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::containing_roland().digest(),
      }
    )
  }

  fn run_command_locally(req: ExecuteProcessRequest) -> Result<ExecuteProcessResult, String> {
    run_command_locally_in_dir(req)
  }

  fn run_command_locally_in_dir(
    req: ExecuteProcessRequest,
  ) -> Result<ExecuteProcessResult, String> {
    let store_dir = TempDir::new("store").unwrap();
    let pool = Arc::new(fs::ResettablePool::new("test-pool-".to_owned()));
    let store = fs::Store::local_only(store_dir.path(), pool.clone()).unwrap();
    let runner = super::CommandRunner {
      store: store,
      fs_pool: pool,
    };
    runner.run(req).wait()
  }

  fn find_bash() -> String {
    which("bash")
      .expect("No bash on PATH")
      .to_str()
      .expect("Path to bash not unicode")
      .to_owned()
  }

  fn which(executable: &str) -> Option<PathBuf> {
    if let Some(paths) = env::var_os("PATH") {
      for path in env::split_paths(&paths) {
        let executable_path = path.join(executable);
        if is_executable(&executable_path) {
          return Some(executable_path);
        }
      }
    }
    None
  }

  fn is_executable(path: &Path) -> bool {
    std::fs::metadata(path)
      .map(|meta| meta.permissions().mode() & 0o100 == 0o100)
      .unwrap_or(false)
  }
}
