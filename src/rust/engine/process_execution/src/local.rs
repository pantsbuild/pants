use log;
use tempfile;

use async_trait::async_trait;
use boxfuture::{try_future, BoxFuture, Boxable};
use fs::{self, GlobExpansionConjunction, GlobMatching, PathGlobs, StrictGlobMatching};
use futures::compat::Future01CompatExt;
use futures::future::{FutureExt, TryFutureExt};
use futures::stream::{BoxStream, StreamExt, TryStreamExt};
use futures01::{future, Future};
use log::{debug, info};
use nails::execution::{ChildOutput, ExitCode};

use std::collections::{BTreeSet, HashSet};
use std::ffi::OsStr;
use std::fs::create_dir_all;
use std::ops::Neg;
use std::os::unix::{fs::symlink, process::ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use store::{OneOffStoreFileByDigest, Snapshot, Store};

use tokio::process::Command;
use tokio::time::timeout;
use tokio_util::codec::{BytesCodec, FramedRead};

use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, Platform, PlatformConstraint,
  Process,
};

use bytes::{Bytes, BytesMut};

#[derive(Clone)]
pub struct CommandRunner {
  pub store: Store,
  executor: task_executor::Executor,
  work_dir_base: PathBuf,
  cleanup_local_dirs: bool,
  platform: Platform,
}

impl CommandRunner {
  pub fn new(
    store: Store,
    executor: task_executor::Executor,
    work_dir_base: PathBuf,
    cleanup_local_dirs: bool,
  ) -> CommandRunner {
    CommandRunner {
      store,
      executor,
      work_dir_base,
      cleanup_local_dirs,
      platform: Platform::current().unwrap(),
    }
  }

  fn platform(&self) -> Platform {
    self.platform
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

    // TODO: should we error when globs fail?
    let output_globs = try_future!(PathGlobs::new(
      try_future!(output_paths),
      StrictGlobMatching::Ignore,
      GlobExpansionConjunction::AllMatch,
    )
    .parse());

    Box::pin(async move {
      let path_stats = posix_fs
        .expand(output_globs)
        .map_err(|err| format!("Error expanding output globs: {}", err))
        .await?;
      Snapshot::from_path_stats(
        store.clone(),
        OneOffStoreFileByDigest::new(store, posix_fs),
        path_stats,
      )
      .await
    })
    .compat()
    .to_boxed()
  }
}

pub struct StreamedHermeticCommand {
  inner: Command,
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

  ///
  /// TODO: See the note on references in ASYNC.md.
  ///
  fn stream<'a, 'b>(
    &'a mut self,
    req: &Process,
  ) -> Result<BoxStream<'b, Result<ChildOutput, String>>, String> {
    self
      .inner
      .stdin(Stdio::null())
      .stdout(Stdio::piped())
      .stderr(Stdio::piped())
      .spawn()
      .map_err(|e| format!("Error launching process: {:?}", e))
      .and_then(|mut child| {
        debug!("spawned local process as {} for {:?}", child.id(), req);
        let stdout_stream = FramedRead::new(child.stdout.take().unwrap(), BytesCodec::new())
          .map_ok(|bytes| ChildOutput::Stdout(bytes.into()))
          .boxed();
        let stderr_stream = FramedRead::new(child.stderr.take().unwrap(), BytesCodec::new())
          .map_ok(|bytes| ChildOutput::Stderr(bytes.into()))
          .boxed();
        let exit_stream = child
          .into_stream()
          .map_ok(|exit_status| {
            ChildOutput::Exit(ExitCode(
              exit_status
                .code()
                .or_else(|| exit_status.signal().map(Neg::neg))
                .expect("Child process should exit via returned code or signal."),
            ))
          })
          .boxed();

        Ok(
          futures::stream::select_all(vec![stdout_stream, stderr_stream, exit_stream])
            .map_err(|e| format!("Failed to consume process outputs: {:?}", e))
            .boxed(),
        )
      })
  }
}

///
/// The fully collected outputs of a completed child process.
///
pub struct ChildResults {
  pub stdout: Bytes,
  pub stderr: Bytes,
  pub exit_code: i32,
}

impl ChildResults {
  pub fn collect_from(
    mut stream: BoxStream<Result<ChildOutput, String>>,
  ) -> futures::future::BoxFuture<Result<ChildResults, String>> {
    let mut stdout = BytesMut::with_capacity(8192);
    let mut stderr = BytesMut::with_capacity(8192);
    let mut exit_code = 1;

    Box::pin(async move {
      while let Some(child_output_res) = stream.next().await {
        match child_output_res? {
          ChildOutput::Stdout(bytes) => stdout.extend_from_slice(&bytes),
          ChildOutput::Stderr(bytes) => stderr.extend_from_slice(&bytes),
          ChildOutput::Exit(code) => exit_code = code.0,
        };
      }
      Ok(ChildResults {
        stdout: stdout.into(),
        stderr: stderr.into(),
        exit_code,
      })
    })
  }
}

#[async_trait]
impl super::CommandRunner for CommandRunner {
  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    for compatible_constraint in vec![
      &(PlatformConstraint::None, PlatformConstraint::None),
      &(self.platform.into(), PlatformConstraint::None),
      &(
        self.platform.into(),
        PlatformConstraint::current_platform_constraint().unwrap(),
      ),
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
  async fn run(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    let req = self.extract_compatible_request(&req).unwrap();
    self
      .run_and_capture_workdir(
        req,
        context,
        self.store.clone(),
        self.executor.clone(),
        self.cleanup_local_dirs,
        &self.work_dir_base,
        self.platform(),
      )
      .compat()
      .await
  }
}

impl CapturedWorkdir for CommandRunner {
  fn run_in_workdir<'a, 'b, 'c>(
    &'a self,
    workdir_path: &'b Path,
    req: Process,
    _context: Context,
  ) -> Result<BoxStream<'c, Result<ChildOutput, String>>, String> {
    StreamedHermeticCommand::new(&req.argv[0])
      .args(&req.argv[1..])
      .current_dir(if let Some(ref working_directory) = req.working_directory {
        workdir_path.join(working_directory)
      } else {
        workdir_path.to_owned()
      })
      .envs(&req.env)
      .stream(&req)
  }
}

pub trait CapturedWorkdir {
  fn run_and_capture_workdir(
    &self,
    req: Process,
    context: Context,
    store: Store,
    executor: task_executor::Executor,
    cleanup_local_dirs: bool,
    workdir_base: &Path,
    platform: Platform,
  ) -> BoxFuture<FallibleProcessResultWithPlatform, String>
  where
    Self: Send + Sync + Clone + 'static,
  {
    let workdir = try_future!(tempfile::Builder::new()
      .prefix("process-execution")
      .tempdir_in(workdir_base)
      .map_err(|err| format!(
        "Error making tempdir for local process execution: {:?}",
        err
      )));

    let workdir_path = workdir.path().to_owned();
    let workdir_path2 = workdir_path.clone();
    let workdir_path3 = workdir_path.clone();
    let workdir_path4 = workdir_path.clone();

    let store2 = store.clone();

    let command_runner = self.clone();
    let req2 = req.clone();
    let output_file_paths = req.output_files;
    let output_file_paths2 = output_file_paths.clone();
    let output_dir_paths = req.output_directories;
    let output_dir_paths2 = output_dir_paths.clone();

    let req_description = req.description;
    let req_timeout = req.timeout;
    let maybe_jdk_home = req.jdk_home;
    let unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule =
      req.unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule;

    store
      .materialize_directory(workdir_path.clone(), req.input_files)
      .and_then({
        move |_metadata| {
          store2.materialize_directory(
            workdir_path4,
            unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule,
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
      .and_then(move |()| command_runner.run_in_workdir(&workdir_path, req2, context))
      // NB: We fully buffer up the `Stream` above into final `ChildResults` below and so could
      // instead be using `CommandExt::output_async` above to avoid the `ChildResults::collect_from`
      // code. The idea going forward though is we eventually want to pass incremental results on
      // down the line for streaming process results to console logs, etc. as tracked by:
      //   https://github.com/pantsbuild/pants/issues/6089
      .map(ChildResults::collect_from)
      .and_then(move |child_results_future| {
        let maybe_timed_out_child_results = Box::pin(async move {
          if let Some(req_timeout) = req_timeout {
            timeout(req_timeout, child_results_future)
              .await
              .map_err(|e| e.to_string())?
          } else {
            child_results_future.await
          }
        });
        maybe_timed_out_child_results.compat()
      })
      .and_then(move |child_results| {
        let output_snapshot = if output_file_paths.is_empty() && output_dir_paths.is_empty() {
          future::ok(store::Snapshot::empty()).to_boxed()
        } else {
          // Use no ignore patterns, because we are looking for explicitly listed paths.
          future::done(fs::GitignoreStyleExcludes::create(vec![]))
            .and_then(|ignorer| future::done(fs::PosixFS::new(workdir_path2, ignorer, executor)))
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
          .map(move |snapshot| FallibleProcessResultWithPlatform {
            stdout: child_results.stdout,
            stderr: child_results.stderr,
            exit_code: child_results.exit_code,
            output_directory: snapshot.digest,
            execution_attempts: vec![],
            platform,
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
        match result {
          Ok(fallible_process_result) => Ok(fallible_process_result),
          Err(msg) => {
            if msg == "deadline has elapsed" {
              Ok(FallibleProcessResultWithPlatform {
                stdout: Bytes::from(format!(
                  "Exceeded timeout of {:?} for local process execution, {}",
                  req_timeout, req_description
                )),
                stderr: Bytes::new(),
                exit_code: -libc::SIGTERM,
                output_directory: hashing::EMPTY_DIGEST,
                execution_attempts: vec![],
                platform,
              })
            } else {
              Err(msg)
            }
          }
        }
      })
      .to_boxed()
  }

  ///
  /// TODO: See the note on references in ASYNC.md.
  ///
  fn run_in_workdir<'a, 'b, 'c>(
    &'a self,
    workdir_path: &'b Path,
    req: Process,
    context: Context,
  ) -> Result<BoxStream<'c, Result<ChildOutput, String>>, String>;
}
