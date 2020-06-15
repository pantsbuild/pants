use async_trait::async_trait;
use boxfuture::{try_future, BoxFuture, Boxable};
use fs::{self, GlobExpansionConjunction, GlobMatching, PathGlobs, StrictGlobMatching};
use futures::compat::Future01CompatExt;
use futures::future::{FutureExt, TryFutureExt};
use futures::stream::{BoxStream, StreamExt, TryStreamExt};
use log::{debug, info};
use nails::execution::{ChildOutput, ExitCode};
use shell_quote::bash;

use std::collections::{BTreeSet, HashSet};
use std::ffi::OsStr;
use std::fs::create_dir_all;
use std::io::Write;
use std::ops::Neg;
use std::os::unix::{
  fs::{symlink, OpenOptionsExt},
  process::ExitStatusExt,
};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::str;
use std::sync::Arc;
use store::{OneOffStoreFileByDigest, Snapshot, Store};

use tokio::process::Command;
use tokio::time::timeout;
use tokio_util::codec::{BytesCodec, FramedRead};

use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, NamedCaches, Platform,
  PlatformConstraint, Process,
};

use bytes::{Bytes, BytesMut};

pub const USER_EXECUTABLE_MODE: u32 = 0o100755;

#[derive(Clone)]
pub struct CommandRunner {
  pub store: Store,
  executor: task_executor::Executor,
  work_dir_base: PathBuf,
  named_caches: NamedCaches,
  cleanup_local_dirs: bool,
  platform: Platform,
}

impl CommandRunner {
  pub fn new(
    store: Store,
    executor: task_executor::Executor,
    work_dir_base: PathBuf,
    named_caches: NamedCaches,
    cleanup_local_dirs: bool,
  ) -> CommandRunner {
    CommandRunner {
      store,
      executor,
      work_dir_base,
      named_caches,
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
      // TODO: This will not universally prevent child processes continuing to run in the
      // background, for a few reasons:
      //   1) the Graph memoizes runs, and generally completes them rather than cancelling them,
      //   2) killing a pantsd client with Ctrl+C kills the server with a signal, which won't
      //      currently result in an orderly dropping of everything in the graph. See #10004.
      .kill_on_drop(true)
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
      .await
  }
}

impl CapturedWorkdir for CommandRunner {
  fn named_caches(&self) -> &NamedCaches {
    &self.named_caches
  }

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

#[async_trait]
pub trait CapturedWorkdir {
  async fn run_and_capture_workdir(
    &self,
    req: Process,
    context: Context,
    store: Store,
    executor: task_executor::Executor,
    cleanup_local_dirs: bool,
    workdir_base: &Path,
    platform: Platform,
  ) -> Result<FallibleProcessResultWithPlatform, String>
  where
    Self: Send + Sync + Clone + 'static,
  {
    // Set up a temporary workdir, which will optionally be preserved.
    let (workdir_path, maybe_workdir) = {
      let workdir = tempfile::Builder::new()
        .prefix("process-execution")
        .tempdir_in(workdir_base)
        .map_err(|err| {
          format!(
            "Error making tempdir for local process execution: {:?}",
            err
          )
        })?;
      if cleanup_local_dirs {
        // Hold on to the workdir so that we can drop it explicitly after we've finished using it.
        (workdir.path().to_owned(), Some(workdir))
      } else {
        // This consumes the `TempDir` without deleting directory on the filesystem, meaning
        // that the temporary directory will no longer be automatically deleted when dropped.
        let preserved_path = workdir.into_path();
        info!(
          "preserving local process execution dir `{:?}` for {:?}",
          preserved_path, req.description
        );
        (preserved_path, None)
      }
    };

    // If named caches are configured, collect the symlinks to create.
    let named_cache_symlinks = self
      .named_caches()
      .local_paths(&req.append_only_caches)
      .collect::<Vec<_>>();

    // Start with async materialization of input snapshots, followed by synchronous materialization
    // of other configured inputs. Note that we don't do this in parallel, as that might cause
    // non-determinism when paths overlap.
    let _metadata = store
      .materialize_directory(workdir_path.clone(), req.input_files)
      .compat()
      .await?;
    let workdir_path2 = workdir_path.clone();
    let output_file_paths = req.output_files.clone();
    let output_dir_paths = req.output_directories.clone();
    let maybe_jdk_home = req.jdk_home.clone();
    executor
      .spawn_blocking(move || {
        if let Some(jdk_home) = maybe_jdk_home {
          symlink(jdk_home, workdir_path2.join(".jdk"))
            .map_err(|err| format!("Error making JDK symlink for local execution: {:?}", err))?
        }

        // The bazel remote execution API specifies that the parent directories for output files and
        // output directories should be created before execution completes: see
        //   https://github.com/pantsbuild/pants/issues/7084.
        // TODO: we use a HashSet to deduplicate directory paths to create, but it would probably be
        // even more efficient to only retain the directories at greatest nesting depth, as
        // create_dir_all() will ensure all parents are created. At that point, we might consider
        // explicitly enumerating all the directories to be created and just using create_dir(),
        // unless there is some optimization in create_dir_all() that makes that less efficient.
        let parent_paths_to_create: HashSet<_> = output_file_paths
          .iter()
          .chain(output_dir_paths.iter())
          .chain(named_cache_symlinks.iter().map(|s| &s.dst))
          .filter_map(|rel_path| rel_path.parent())
          .map(|parent_relpath| workdir_path2.join(parent_relpath))
          .collect();
        for path in parent_paths_to_create {
          create_dir_all(path.clone()).map_err(|err| {
            format!(
              "Error making parent directory {:?} for local execution: {:?}",
              path, err
            )
          })?;
        }

        for named_cache_symlink in named_cache_symlinks {
          symlink(
            &named_cache_symlink.src,
            workdir_path2.join(&named_cache_symlink.dst),
          )
          .map_err(|err| {
            format!(
              "Error making {:?} for local execution: {:?}",
              named_cache_symlink, err
            )
          })?;
        }

        let res: Result<_, String> = Ok(());
        res
      })
      .await?;

    // Spawn the process.
    // NB: We fully buffer up the `Stream` above into final `ChildResults` below and so could
    // instead be using `CommandExt::output_async` above to avoid the `ChildResults::collect_from`
    // code. The idea going forward though is we eventually want to pass incremental results on
    // down the line for streaming process results to console logs, etc. as tracked by:
    //   https://github.com/pantsbuild/pants/issues/6089
    let child_results_result = {
      let child_results_future =
        ChildResults::collect_from(self.run_in_workdir(&workdir_path, req.clone(), context)?);
      if let Some(req_timeout) = req.timeout {
        timeout(req_timeout, child_results_future)
          .await
          .map_err(|e| e.to_string())
          .and_then(|r| r)
      } else {
        child_results_future.await
      }
    };

    // Capture the process outputs, and optionally clean up the workdir.
    let output_snapshot = if req.output_files.is_empty() && req.output_directories.is_empty() {
      store::Snapshot::empty()
    } else {
      // Use no ignore patterns, because we are looking for explicitly listed paths.
      let posix_fs = Arc::new(
        fs::PosixFS::new(
          workdir_path.clone(),
          fs::GitignoreStyleExcludes::empty(),
          executor.clone(),
        )
        .map_err(|err| {
          format!(
            "Error making posix_fs to fetch local process execution output files: {}",
            err
          )
        })?,
      );
      CommandRunner::construct_output_snapshot(
        store.clone(),
        posix_fs,
        req.output_files,
        req.output_directories,
      )
      .compat()
      .await?
    };

    match maybe_workdir {
      Some(workdir) => {
        // Dropping the temporary directory will likely involve a lot of IO: do it in the
        // background.
        let _background_cleanup = executor.spawn_blocking(|| std::mem::drop(workdir));
      }
      None => {
        // If we don't cleanup the workdir, we materialize a file named `__run.sh` into the output
        // directory with command-line arguments and environment variables.
        let mut env_var_strings: Vec<String> = vec![];
        for (key, value) in req.env.iter() {
          let quoted_arg = bash::escape(&value);
          let arg_str = str::from_utf8(&quoted_arg)
            .map_err(|e| format!("{:?}", e))?
            .to_string();
          let formatted_assignment = format!("{}={}", key, arg_str);
          env_var_strings.push(formatted_assignment);
        }
        let stringified_env_vars: String = env_var_strings.join(" ");

        // Shell-quote every command-line argument, as necessary.
        let mut full_command_line: Vec<String> = vec![];
        for arg in req.argv.iter() {
          let quoted_arg = bash::escape(&arg);
          let arg_str = str::from_utf8(&quoted_arg)
            .map_err(|e| format!("{:?}", e))?
            .to_string();
          full_command_line.push(arg_str);
        }

        let stringified_command_line: String = full_command_line.join(" ");
        let full_script = format!(
          "#!/bin/bash
# This command line should execute the same process as pants did internally.
export {}

{}
",
          stringified_env_vars, stringified_command_line,
        );

        let full_file_path = workdir_path.join("__run.sh");

        ::std::fs::OpenOptions::new()
          .create_new(true)
          .write(true)
          .mode(USER_EXECUTABLE_MODE) // Executable for user, read-only for others.
          .open(&full_file_path)
          .map_err(|e| format!("{:?}", e))?
          .write_all(full_script.as_bytes())
          .map_err(|e| format!("{:?}", e))?;
      }
    }

    match child_results_result {
      Ok(child_results) => {
        let stdout = child_results.stdout;
        let stdout_digest = store.store_file_bytes(stdout.clone(), true).await?;

        let stderr = child_results.stderr;
        let stderr_digest = store.store_file_bytes(stderr.clone(), true).await?;

        Ok(FallibleProcessResultWithPlatform {
          stdout_digest,
          stderr_digest,
          exit_code: child_results.exit_code,
          output_directory: output_snapshot.digest,
          execution_attempts: vec![],
          platform,
        })
      }
      Err(msg) => {
        if msg == "deadline has elapsed" {
          let stdout = Bytes::from(format!(
            "Exceeded timeout of {:?} for local process execution, {}",
            req.timeout, req.description
          ));
          let stdout_digest = store.store_file_bytes(stdout.clone(), true).await?;

          Ok(FallibleProcessResultWithPlatform {
            stdout_digest,
            stderr_digest: hashing::EMPTY_DIGEST,
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
  }

  fn named_caches(&self) -> &NamedCaches;

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
