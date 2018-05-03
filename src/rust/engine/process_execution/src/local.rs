extern crate tempdir;

use boxfuture::{BoxFuture, Boxable};
use fs::{self, VFS};
use futures::{future, Future};
use hashing;
use std::path::Path;
use std::process::Command;
use std::sync::Arc;

use super::{ExecuteProcessRequest, ExecuteProcessResult};

use bytes::Bytes;

// TODO: Move this into boxfuture or somewhere.
macro_rules! try_future {
( $x:expr) => {
    {
        match $x {
            Ok(value) => {value}
            Err(error) => {return future::err(error).to_boxed();}
        }
    }
};
}

pub struct CommandRunner {
  // TODO: Not public
  pub store: fs::Store,
  pub fs_pool: Arc<fs::ResettablePool>,
}

impl CommandRunner {
  ///
  /// Runs a command on this machine in the pwd.
  ///
  pub fn run(
    &self,
    req: ExecuteProcessRequest,
    workdir: &Path,
  ) -> BoxFuture<ExecuteProcessResult, String> {
    let output = try_future!(
      Command::new(&req.argv[0])
        .args(&req.argv[1..])
        .current_dir(workdir)
        .env_clear()
        // It would be really nice not to have to manually set PATH but this is sadly the only way
        // to stop automatic PATH searching.
        .env("PATH", "")
        .envs(req.env)
        .output().map_err(|e| format!("Error executing process: {:?}", e))
    );

    let output_directory_digest = if req.output_files.is_empty() {
      future::ok(fs::EMPTY_DIGEST).to_boxed()
    } else {
      // TODO: Extract the commonality between this and fs_util into... Somewhere.
      let posix_fs = Arc::new(fs::PosixFS::new(workdir, self.fs_pool.clone(), vec![]).unwrap());
      let store = self.store.clone();
      posix_fs
        .expand(try_future!(fs::PathGlobs::create(
          // TODO: Make sure files don't have glob patterns in them
          &req
            .output_files
            .iter()
            .map(|path| path.to_string_lossy().to_string())
            .collect::<Vec<String>>(),
          &[],
        )))
        .map_err(|e| format!("Error expanding globs: {}", e))
        .and_then(move |paths| {
          fs::Snapshot::from_path_stats(store.clone(), FileSaver { store, posix_fs }, paths)
        })
        .map(|snapshot| snapshot.digest)
        .to_boxed()
    };

    output_directory_digest
      .map(|digest| ExecuteProcessResult {
        stdout: Bytes::from(output.stdout),
        stderr: Bytes::from(output.stderr),
        exit_code: output.status.code().unwrap(),
        output_directory: digest,
      })
      .to_boxed()
  }
}

#[derive(Clone)]
struct FileSaver {
  store: fs::Store,
  posix_fs: Arc<fs::PosixFS>,
}

impl fs::StoreFileByDigest<String> for FileSaver {
  fn store_by_digest(&self, file: &fs::File) -> BoxFuture<hashing::Digest, String> {
    let file_copy = file.clone();
    let store = self.store.clone();
    self
      .posix_fs
      .read_file(&file)
      .map_err(move |err| format!("Error reading file {:?}: {:?}", file_copy, err))
      .and_then(move |content| store.store_file_bytes(content.content, true))
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
    let working_dir = TempDir::new("working").unwrap();

    let content = TestData::roland();
    let directory = TestDirectory::containing_roland();

    let result = run_command_locally_in_dir(
      ExecuteProcessRequest {
        argv: vec![
          find_bash(),
          "-c".to_owned(),
          format!("echo -n {} > {}", content.string(), "roland"),
        ],
        env: BTreeMap::new(),
        input_files: fs::EMPTY_DIGEST,
        output_files: vec![PathBuf::from("roland")].into_iter().collect(),
      },
      working_dir.path(),
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
    run_command_locally_in_dir(req, &PathBuf::from("/"))
  }

  fn run_command_locally_in_dir(
    req: ExecuteProcessRequest,
    dir: &Path,
  ) -> Result<ExecuteProcessResult, String> {
    let store_dir = TempDir::new("store").unwrap();
    let pool = Arc::new(fs::ResettablePool::new("test-pool-".to_owned()));
    let store = fs::Store::local_only(store_dir.path(), pool.clone()).unwrap();
    let runner = super::CommandRunner {
      store: store,
      fs_pool: pool,
    };
    runner.run(req, dir).wait()
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
