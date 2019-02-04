use log;
use tempfile;

use boxfuture::{try_future, BoxFuture, Boxable};
use fs::{self, GlobExpansionConjunction, GlobMatching, PathGlobs, Snapshot, StrictGlobMatching};
use futures::{future, Future, Stream};
use log::info;
use std::collections::{BTreeSet, HashSet};
use std::ffi::OsStr;
use std::fs::create_dir_all;
use std::ops::Neg;
use std::os::unix::{fs::symlink, process::ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Arc;

use tokio_codec::{BytesCodec, FramedRead};
use tokio_process::CommandExt;

use super::{ExecuteProcessRequest, FallibleExecuteProcessResult};

use bytes::{Bytes, BytesMut};

pub struct CommandRunner {
  store: fs::Store,
  fs_pool: Arc<fs::ResettablePool>,
  work_dir: PathBuf,
  cleanup_local_dirs: bool,
}

impl CommandRunner {
  pub fn new(
    store: fs::Store,
    fs_pool: Arc<fs::ResettablePool>,
    work_dir: PathBuf,
    cleanup_local_dirs: bool,
  ) -> CommandRunner {
    CommandRunner {
      store,
      fs_pool,
      work_dir,
      cleanup_local_dirs,
    }
  }

  fn construct_output_snapshot(
    store: fs::Store,
    posix_fs: Arc<fs::PosixFS>,
    output_file_paths: BTreeSet<PathBuf>,
    output_dir_paths: BTreeSet<PathBuf>,
  ) -> BoxFuture<Snapshot, String> {
    let output_paths: Result<Vec<String>, String> = output_dir_paths
      .into_iter()
      .flat_map(|p| {
        let mut dir = p.into_os_string();
        let dir_glob = dir.clone();
        dir.push("/**");
        vec![dir_glob, dir]
      })
      .chain(output_file_paths.into_iter().map(|p| p.into_os_string()))
      .map(|s| {
        s.into_string()
          .map_err(|e| format!("Error stringifying output paths: {:?}", e))
      })
      .collect();

    let output_globs = try_future!(PathGlobs::create(
      &try_future!(output_paths),
      &[],
      StrictGlobMatching::Ignore,
      GlobExpansionConjunction::AllMatch,
    ));

    posix_fs
      .expand(output_globs)
      .map_err(|err| format!("Error expanding output globs: {}", err))
      .and_then(|path_stats| {
        fs::Snapshot::from_path_stats(
          store.clone(),
          &fs::OneOffStoreFileByDigest::new(store, posix_fs),
          path_stats,
        )
      })
      .to_boxed()
  }
}

struct StreamedHermeticCommand {
  inner: Command,
}

///
/// The possible incremental outputs of a spawned child process.
///
#[derive(Debug)]
enum ChildOutput {
  Stdout(Bytes),
  Stderr(Bytes),
  Exit(i32),
}

///
/// A streaming command that accepts no input stream and does not consult the `PATH`.
///
impl StreamedHermeticCommand {
  fn new<S: AsRef<OsStr>>(program: S) -> StreamedHermeticCommand {
    let mut inner = Command::new(program);
    inner
      .env_clear()
      // It would be really nice not to have to manually set PATH but this is sadly the only way
      // to stop automatic PATH searching.
      .env("PATH", "");
    StreamedHermeticCommand { inner }
  }

  fn args<I, S>(&mut self, args: I) -> &mut StreamedHermeticCommand
  where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
  {
    self.inner.args(args);
    self
  }

  fn envs<I, K, V>(&mut self, vars: I) -> &mut StreamedHermeticCommand
  where
    I: IntoIterator<Item = (K, V)>,
    K: AsRef<OsStr>,
    V: AsRef<OsStr>,
  {
    self.inner.envs(vars);
    self
  }

  fn current_dir<P: AsRef<Path>>(&mut self, dir: P) -> &mut StreamedHermeticCommand {
    self.inner.current_dir(dir);
    self
  }

  fn stream(&mut self) -> Result<impl Stream<Item = ChildOutput, Error = String> + Send, String> {
    self
      .inner
      .stdin(Stdio::null())
      .stdout(Stdio::piped())
      .stderr(Stdio::piped())
      .spawn_async()
      .map_err(|e| format!("Error launching process: {:?}", e))
      .and_then(|mut child| {
        let stdout_stream = FramedRead::new(child.stdout().take().unwrap(), BytesCodec::new())
          .map(|bytes| ChildOutput::Stdout(bytes.into()));
        let stderr_stream = FramedRead::new(child.stderr().take().unwrap(), BytesCodec::new())
          .map(|bytes| ChildOutput::Stderr(bytes.into()));
        let exit_stream = child.into_stream().map(|exit_status| {
          ChildOutput::Exit(
            exit_status
              .code()
              .or_else(|| exit_status.signal().map(Neg::neg))
              .expect("Child process should exit via returned code or signal."),
          )
        });

        Ok(
          stdout_stream
            .select(stderr_stream)
            .select(exit_stream)
            .map_err(|e| format!("Failed to consume process outputs: {:?}", e)),
        )
      })
  }
}

///
/// The fully collected outputs of a completed child process.
///
struct ChildResults {
  stdout: Bytes,
  stderr: Bytes,
  exit_code: i32,
}

impl ChildResults {
  fn collect_from<E>(
    stream: impl Stream<Item = ChildOutput, Error = E> + Send,
  ) -> impl Future<Item = ChildResults, Error = E> {
    let init = (
      BytesMut::with_capacity(8192),
      BytesMut::with_capacity(8192),
      0,
    );
    stream
      .fold(
        init,
        |(mut stdout, mut stderr, mut exit_code), child_output| {
          match child_output {
            ChildOutput::Stdout(bytes) => stdout.extend_from_slice(&bytes),
            ChildOutput::Stderr(bytes) => stderr.extend_from_slice(&bytes),
            ChildOutput::Exit(code) => exit_code = code,
          };
          Ok((stdout, stderr, exit_code)) as Result<_, E>
        },
      )
      .map(|(stdout, stderr, exit_code)| ChildResults {
        stdout: stdout.into(),
        stderr: stderr.into(),
        exit_code,
      })
  }
}

impl super::CommandRunner for CommandRunner {
  ///
  /// Runs a command on this machine in the passed working directory.
  ///
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let workdir = try_future!(tempfile::Builder::new()
      .prefix("process-execution")
      .tempdir_in(&self.work_dir)
      .map_err(|err| format!(
        "Error making tempdir for local process execution: {:?}",
        err
      )));
    let workdir_path = workdir.path().to_owned();
    let workdir_path2 = workdir_path.clone();
    let workdir_path3 = workdir_path.clone();
    let store = self.store.clone();
    let fs_pool = self.fs_pool.clone();

    let env = req.env;
    let output_file_paths = req.output_files;
    let output_file_paths2 = output_file_paths.clone();
    let output_dir_paths = req.output_directories;
    let output_dir_paths2 = output_dir_paths.clone();
    let cleanup_local_dirs = self.cleanup_local_dirs;
    let argv = req.argv;
    let req_description = req.description;
    let maybe_jdk_home = req.jdk_home;
    self
      .store
      .materialize_directory(workdir_path.clone(), req.input_files)
      .and_then(move |()| {
        maybe_jdk_home.map_or(Ok(()), |jdk_home| {
          symlink(jdk_home, workdir_path3.clone().join(".jdk"))
            .map_err(|err| format!("Error making symlink for local execution: {:?}", err))
        })?;
        // The bazel remote execution API specifies that the parent directories for output files and
        // output directories should be created before execution completes: see
        //   https://github.com/pantsbuild/pants/issues/7084.
        let parent_paths_to_create: HashSet<_> = output_file_paths2
          .iter()
          .chain(output_dir_paths2.iter())
          .filter_map(|rel_path| rel_path.parent())
          .map(|parent_relpath| workdir_path3.join(parent_relpath))
          .collect();
        // TODO: we use a HashSet to deduplicate directory paths to create, but it would probably be
        // even more efficient to only retain the directories at greatest nesting depth, as
        // create_dir_all() will ensure all parents are created. At that point, we might consider
        // explicitly enumerating all the directories to be created and just using create_dir(),
        // unless there is some optimization in create_dir_all() that makes that less efficient.
        for path in parent_paths_to_create {
          create_dir_all(path.clone()).map_err(|err| {
            format!(
              "Error making parent directory {:?} for local execution: {:?}",
              path, err
            )
          })?;
        }
        Ok(())
      })
      .and_then(move |()| {
        StreamedHermeticCommand::new(&argv[0])
          .args(&argv[1..])
          .current_dir(&workdir_path)
          .envs(env)
          .stream()
      })
      // NB: We fully buffer up the `Stream` above into final `ChildResults` below and so could
      // instead be using `CommandExt::output_async` above to avoid the `ChildResults::collect_from`
      // code. The idea going forward though is we eventually want to pass incremental results on
      // down the line for streaming process results to console logs, etc. as tracked by:
      //   https://github.com/pantsbuild/pants/issues/6089
      .and_then(ChildResults::collect_from)
      .and_then(move |child_results| {
        let output_snapshot = if output_file_paths.is_empty() && output_dir_paths.is_empty() {
          future::ok(fs::Snapshot::empty()).to_boxed()
        } else {
          // Use no ignore patterns, because we are looking for explicitly listed paths.
          future::done(fs::PosixFS::new(workdir_path2, fs_pool, &[]))
            .map_err(|err| {
              format!(
                "Error making posix_fs to fetch local process execution output files: {}",
                err
              )
            })
            .map(Arc::new)
            .and_then(|posix_fs| {
              CommandRunner::construct_output_snapshot(
                store,
                posix_fs,
                output_file_paths,
                output_dir_paths,
              )
            })
            .to_boxed()
        };

        output_snapshot
          .map(move |snapshot| FallibleExecuteProcessResult {
            stdout: child_results.stdout,
            stderr: child_results.stderr,
            exit_code: child_results.exit_code,
            output_directory: snapshot.digest,
            execution_attempts: vec![],
          })
          .to_boxed()
      })
      .then(move |result| {
        // Force workdir not to get dropped until after we've ingested the outputs
        if !cleanup_local_dirs {
          // This consumes the `TempDir` without deleting directory on the filesystem, meaning
          // that the temporary directory will no longer be automatically deleted when dropped.
          let preserved_path = workdir.into_path();
          info!(
            "preserved local process execution dir `{:?}` for {:?}",
            preserved_path, req_description
          );
        } // Else, workdir gets dropped here
        result
      })
      .to_boxed()
  }
}

#[cfg(test)]
mod tests {
  use tempfile;
  use testutil;

  use super::super::CommandRunner as CommandRunnerTrait;
  use super::{ExecuteProcessRequest, FallibleExecuteProcessResult};
  use fs;
  use futures::Future;
  use std;
  use std::collections::{BTreeMap, BTreeSet};
  use std::env;
  use std::os::unix::fs::PermissionsExt;
  use std::path::{Path, PathBuf};
  use std::sync::Arc;
  use std::time::Duration;
  use tempfile::TempDir;
  use testutil::data::{TestData, TestDirectory};
  use testutil::{as_bytes, owned_string_vec};

  #[test]
  #[cfg(unix)]
  fn stdout() {
    let result = run_command_locally(ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "echo foo".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
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
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "echo foo and fail".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes("bar"),
        exit_code: 1,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      }
    )
  }

  #[test]
  #[cfg(unix)]
  fn capture_exit_code_signal() {
    // Launch a process that kills itself with a signal.
    let result = run_command_locally(ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/bash", "-c", "kill $$"]),
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "kill self".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: -15,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
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
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "run env".to_string(),
      jdk_home: None,
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
        output_directories: BTreeSet::new(),
        timeout: Duration::from_millis(1000),
        description: "run env".to_string(),
        jdk_home: None,
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
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "echo foo".to_string(),
      jdk_home: None,
    })
    .expect_err("Want Err");
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
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "bash".to_string(),
      jdk_home: None,
    });
    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      }
    )
  }

  #[test]
  fn output_files_one() {
    let result = run_command_locally(ExecuteProcessRequest {
      argv: vec![
        find_bash(),
        "-c".to_owned(),
        format!("echo -n {} > {}", TestData::roland().string(), "roland"),
      ],
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: vec![PathBuf::from("roland")].into_iter().collect(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "bash".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::containing_roland().digest(),
        execution_attempts: vec![],
      }
    )
  }

  #[test]
  fn output_dirs() {
    let result = run_command_locally(ExecuteProcessRequest {
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
      input_files: fs::EMPTY_DIGEST,
      output_files: vec![PathBuf::from("treats")].into_iter().collect(),
      output_directories: vec![PathBuf::from("cats")].into_iter().collect(),
      timeout: Duration::from_millis(1000),
      description: "bash".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::recursive().digest(),
        execution_attempts: vec![],
      }
    )
  }

  #[test]
  fn output_files_many() {
    let result = run_command_locally(ExecuteProcessRequest {
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
      input_files: fs::EMPTY_DIGEST,
      output_files: vec![PathBuf::from("cats/roland"), PathBuf::from("treats")]
        .into_iter()
        .collect(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "treats-roland".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::recursive().digest(),
        execution_attempts: vec![],
      }
    )
  }

  #[test]
  fn output_files_execution_failure() {
    let result = run_command_locally(ExecuteProcessRequest {
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
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "echo foo".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 1,
        output_directory: TestDirectory::containing_roland().digest(),
        execution_attempts: vec![],
      }
    )
  }

  #[test]
  fn output_files_partial_output() {
    let result = run_command_locally(ExecuteProcessRequest {
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
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "echo-roland".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::containing_roland().digest(),
        execution_attempts: vec![],
      }
    )
  }

  #[test]
  fn output_overlapping_file_and_dir() {
    let result = run_command_locally(ExecuteProcessRequest {
      argv: vec![
        find_bash(),
        "-c".to_owned(),
        format!("echo -n {} > cats/roland", TestData::roland().string()),
      ],
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: vec![PathBuf::from("cats/roland")].into_iter().collect(),
      output_directories: vec![PathBuf::from("cats")].into_iter().collect(),
      timeout: Duration::from_millis(1000),
      description: "bash".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::nested().digest(),
        execution_attempts: vec![],
      }
    )
  }

  #[test]
  fn jdk_symlink() {
    let preserved_work_tmpdir = TempDir::new().unwrap();
    let roland = TestData::roland().bytes();
    std::fs::write(preserved_work_tmpdir.path().join("roland"), roland.clone())
      .expect("Writing temporary file");

    let result = run_command_locally(ExecuteProcessRequest {
      argv: vec!["/bin/cat".to_owned(), ".jdk/roland".to_owned()],
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "cat roland".to_string(),
      jdk_home: Some(preserved_work_tmpdir.path().to_path_buf()),
    });
    assert_eq!(
      result,
      Ok(FallibleExecuteProcessResult {
        stdout: roland,
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: fs::EMPTY_DIGEST,
        execution_attempts: vec![],
      })
    )
  }

  #[test]
  fn test_directory_preservation() {
    let preserved_work_tmpdir = TempDir::new().unwrap();
    let preserved_work_root = preserved_work_tmpdir.path().to_owned();

    let result = run_command_locally_in_dir(
      ExecuteProcessRequest {
        argv: vec![
          find_bash(),
          "-c".to_owned(),
          format!("echo -n {} > {}", TestData::roland().string(), "roland"),
        ],
        env: BTreeMap::new(),
        input_files: fs::EMPTY_DIGEST,
        output_files: vec![PathBuf::from("roland")].into_iter().collect(),
        output_directories: BTreeSet::new(),
        timeout: Duration::from_millis(1000),
        description: "bash".to_string(),
        jdk_home: None,
      },
      preserved_work_root.clone(),
      false,
    );
    result.unwrap();

    assert!(preserved_work_root.exists());

    // Collect all of the top level sub-dirs under our test workdir.
    let subdirs = testutil::file::list_dir(&preserved_work_root);
    assert_eq!(subdirs.len(), 1);

    // Then look for a file like e.g. `/tmp/abc1234/process-execution7zt4pH/roland`
    let rolands_path = preserved_work_root.join(&subdirs[0]).join("roland");
    assert!(rolands_path.exists());
  }

  #[test]
  fn test_directory_preservation_error() {
    let preserved_work_tmpdir = TempDir::new().unwrap();
    let preserved_work_root = preserved_work_tmpdir.path().to_owned();

    assert!(preserved_work_root.exists());
    assert_eq!(testutil::file::list_dir(&preserved_work_root).len(), 0);

    run_command_locally_in_dir(
      ExecuteProcessRequest {
        argv: vec!["doesnotexist".to_owned()],
        env: BTreeMap::new(),
        input_files: fs::EMPTY_DIGEST,
        output_files: BTreeSet::new(),
        output_directories: BTreeSet::new(),
        timeout: Duration::from_millis(1000),
        description: "failing execution".to_string(),
        jdk_home: None,
      },
      preserved_work_root.clone(),
      false,
    )
    .expect_err("Want process to fail");

    assert!(preserved_work_root.exists());
    // Collect all of the top level sub-dirs under our test workdir.
    assert_eq!(testutil::file::list_dir(&preserved_work_root).len(), 1);
  }

  #[test]
  fn all_containing_directories_for_outputs_are_created() {
    let result = run_command_locally(ExecuteProcessRequest {
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
      input_files: fs::EMPTY_DIGEST,
      output_files: vec![PathBuf::from("cats/roland")].into_iter().collect(),
      output_directories: vec![PathBuf::from("birds/falcons")].into_iter().collect(),
      timeout: Duration::from_millis(1000),
      description: "create nonoverlapping directories and file".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::nested_dir_and_file().digest(),
        execution_attempts: vec![],
      }
    )
  }

  #[test]
  fn output_empty_dir() {
    let result = run_command_locally(ExecuteProcessRequest {
      argv: vec![
        find_bash(),
        "-c".to_owned(),
        "/bin/mkdir falcons".to_string(),
      ],
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: vec![PathBuf::from("falcons")].into_iter().collect(),
      timeout: Duration::from_millis(1000),
      description: "bash".to_string(),
      jdk_home: None,
    });

    assert_eq!(
      result.unwrap(),
      FallibleExecuteProcessResult {
        stdout: as_bytes(""),
        stderr: as_bytes(""),
        exit_code: 0,
        output_directory: TestDirectory::containing_falcons_dir().digest(),
        execution_attempts: vec![],
      }
    )
  }

  fn run_command_locally(
    req: ExecuteProcessRequest,
  ) -> Result<FallibleExecuteProcessResult, String> {
    let work_dir = TempDir::new().unwrap();
    run_command_locally_in_dir_with_cleanup(req, work_dir.path().to_owned())
  }

  fn run_command_locally_in_dir_with_cleanup(
    req: ExecuteProcessRequest,
    dir: PathBuf,
  ) -> Result<FallibleExecuteProcessResult, String> {
    run_command_locally_in_dir(req, dir, true)
  }

  fn run_command_locally_in_dir(
    req: ExecuteProcessRequest,
    dir: PathBuf,
    cleanup: bool,
  ) -> Result<FallibleExecuteProcessResult, String> {
    let store_dir = TempDir::new().unwrap();
    let pool = Arc::new(fs::ResettablePool::new("test-pool-".to_owned()));
    let store = fs::Store::local_only(store_dir.path(), pool.clone()).unwrap();
    let runner = super::CommandRunner {
      store: store,
      fs_pool: pool,
      work_dir: dir,
      cleanup_local_dirs: cleanup,
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
