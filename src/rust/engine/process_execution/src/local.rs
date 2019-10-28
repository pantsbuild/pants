use log;
use tempfile;

use boxfuture::{try_future, BoxFuture, Boxable};
use fs::{self, GlobExpansionConjunction, GlobMatching, PathGlobs, StrictGlobMatching};
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
use store::{OneOffStoreFileByDigest, Snapshot, Store};

use tokio_codec::{BytesCodec, FramedRead};
use tokio_process::CommandExt;

use crate::{
  Context, ExecuteProcessRequest, FallibleExecuteProcessResult, MultiPlatformExecuteProcessRequest,
  Platform,
};

use bytes::{Bytes, BytesMut};
use workunit_store::WorkUnitStore;

pub struct CommandRunner {
  pub store: Store,
  executor: task_executor::Executor,
  pub work_dir: PathBuf,
  cleanup_local_dirs: bool,
  platform: Platform,
}

impl CommandRunner {
  pub fn new(
    store: Store,
    executor: task_executor::Executor,
    work_dir: PathBuf,
    cleanup_local_dirs: bool,
  ) -> CommandRunner {
    CommandRunner {
      store,
      executor,
      work_dir,
      cleanup_local_dirs,
      platform: Platform::current_platform().unwrap(),
    }
  }

  fn construct_output_snapshot(
    store: Store,
    posix_fs: Arc<fs::PosixFS>,
    output_file_paths: BTreeSet<PathBuf>,
    output_dir_paths: BTreeSet<PathBuf>,
  ) -> BoxFuture<Snapshot, String> {
    let output_paths: Result<Vec<String>, String> = output_dir_paths
      .into_iter()
      .flat_map(|p| {
        let mut dir_glob = p.into_os_string();
        let dir = dir_glob.clone();
        dir_glob.push("/**");
        vec![dir, dir_glob]
      })
      .chain(output_file_paths.into_iter().map(PathBuf::into_os_string))
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
        Snapshot::from_path_stats(
          store.clone(),
          &OneOffStoreFileByDigest::new(store, posix_fs),
          path_stats,
          WorkUnitStore::new(),
        )
      })
      .to_boxed()
  }
}

pub struct StreamedHermeticCommand {
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
  fn extract_compatible_request(
    &self,
    req: &MultiPlatformExecuteProcessRequest,
  ) -> Option<ExecuteProcessRequest> {
    for compatible_constraint in vec![
      &(Platform::None, Platform::None),
      &(self.platform, Platform::None),
      &(self.platform, Platform::current_platform().unwrap()),
    ]
    .iter()
    {
      if let Some(compatible_req) = req.0.get(compatible_constraint) {
        return Some(compatible_req.clone());
      }
    }
    None
  }

  ///
  /// Runs a command on this machine in the passed working directory.
  ///
  /// TODO: start to create workunits for local process execution
  ///
  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let workdir = try_future!(tempfile::Builder::new()
      .prefix("process-execution")
      .tempdir_in(&self.work_dir)
      .map_err(|err| format!(
        "Error making tempdir for local process execution: {:?}",
        err
      )));
    let req = self.extract_compatible_request(&req).unwrap();
    let workdir_path = workdir.path().to_owned();
    let workdir_path2 = workdir_path.clone();
    let workdir_path3 = workdir_path.clone();
    let workdir_path4 = workdir_path.clone();
    let store = self.store.clone();
    let store2 = self.store.clone();
    let executor = self.executor.clone();

    let env = req.env;
    let output_file_paths = req.output_files;
    let output_file_paths2 = output_file_paths.clone();
    let output_dir_paths = req.output_directories;
    let output_dir_paths2 = output_dir_paths.clone();
    let cleanup_local_dirs = self.cleanup_local_dirs;
    let argv = req.argv;
    let req_description = req.description;
    let maybe_jdk_home = req.jdk_home;
    let unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule =
      req.unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule;

    self
      .store
      .materialize_directory(
        workdir_path.clone(),
        req.input_files,
        context.workunit_store.clone(),
      )
      .and_then({
        let workunit_store = context.workunit_store.clone();
        move |_metadata| {
          store2.materialize_directory(
            workdir_path4,
            unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule,
            workunit_store,
          )
        }
      })
      .and_then(move |_metadata| {
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
          future::ok(store::Snapshot::empty()).to_boxed()
        } else {
          // Use no ignore patterns, because we are looking for explicitly listed paths.
          future::done(fs::PosixFS::new(workdir_path2, &[], executor))
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
