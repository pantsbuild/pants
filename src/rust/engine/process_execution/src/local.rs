extern crate tempdir;

use boxfuture::{BoxFuture, Boxable};
use fs::{self, PathStatGetter};
use futures::{future, Future};
use std::process::Command;
use std::sync::Arc;

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

  ///
  /// Runs a command on this machine in the passed working directory.
  ///
  /// This takes ownership of a TempDir rather than a Path to ensure that the TempDir can't be
  /// dropped, and thus the underlying directory deleted, while we need a reference to it. If we
  /// switch to not use TempDir, we should ensure that this guarantee still holds.
  ///
  pub fn run(
    &self,
    req: ExecuteProcessRequest,
    workdir: tempdir::TempDir,
  ) -> BoxFuture<ExecuteProcessResult, String> {
    let env = req.env;
    let output_file_paths = req.output_files;
    let output = try_future!(
      Command::new(&req.argv[0])
        .args(&req.argv[1..])
        .current_dir(workdir.path())
        .env_clear()
        // It would be really nice not to have to manually set PATH but this is sadly the only way
        // to stop automatic PATH searching.
        .env("PATH", "")
        .envs(env)
        .output().map_err(|e| format!("Error executing process: {:?}", e))
    );

    let output_snapshot = if output_file_paths.is_empty() {
      future::ok(fs::Snapshot::empty()).to_boxed()
    } else {
      let store = self.store.clone();
      // Use no ignore patterns, because we are looking for explicitly listed paths.
      future::done(fs::PosixFS::new(
        workdir.path(),
        self.fs_pool.clone(),
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
            .path_stats(output_file_paths)
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
  }
}

#[cfg(test)]
mod tests {
  extern crate tempdir;
  extern crate testutil;

  use fs;
  use futures::Future;
  use super::{ExecuteProcessRequest, ExecuteProcessResult};
  use std;
  use std::collections::BTreeMap;
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
      output_files: vec![],
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
      output_files: vec![],
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
      output_files: vec![],
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
        output_files: vec![],
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
      output_files: vec![],
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
      output_files: vec![],
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
    let working_dir = TempDir::new("working").unwrap();

    let content = TestData::roland();
    let directory = TestDirectory::containing_roland();
    let output_file_path = PathBuf::from("roland");

    let result = run_command_locally_in_dir(
      ExecuteProcessRequest {
        argv: vec![
          find_bash(),
          "-c".to_owned(),
          format!("echo -n {} > {}", content.string(), "roland"),
        ],
        env: BTreeMap::new(),
        input_files: fs::EMPTY_DIGEST,
        output_files: vec![output_file_path.clone()],
      },
      working_dir,
    );

    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: directory.digest(),
      }
    )
  }

  #[test]
  fn output_files_many() {
    // TODO
  }

  #[test]
  fn output_files_failure() {
    // TODO
  }

  fn run_command_locally(req: ExecuteProcessRequest) -> Result<ExecuteProcessResult, String> {
    run_command_locally_in_dir(
      req,
      TempDir::new("process-execution").expect("Creating tempdir"),
    )
  }

  fn run_command_locally_in_dir(
    req: ExecuteProcessRequest,
    workdir: tempdir::TempDir,
  ) -> Result<ExecuteProcessResult, String> {
    let store_dir = TempDir::new("store").unwrap();
    let pool = Arc::new(fs::ResettablePool::new("test-pool-".to_owned()));
    let store = fs::Store::local_only(store_dir.path(), pool.clone()).unwrap();
    let runner = super::CommandRunner {
      store: store,
      fs_pool: pool,
    };
    runner.run(req, workdir).wait()
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
