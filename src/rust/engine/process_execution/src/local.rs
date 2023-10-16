// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fmt::{self, Debug};
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
use std::time::Instant;

use async_trait::async_trait;
use bytes::{Bytes, BytesMut};
use fs::{
    self, safe_create_dir_all_ioerror, DirectoryDigest, GlobExpansionConjunction, GlobMatching,
    PathGlobs, Permissions, RelativePath, StrictGlobMatching, EMPTY_DIRECTORY_DIGEST,
};
use futures::stream::{BoxStream, StreamExt, TryStreamExt};
use futures::{try_join, FutureExt, TryFutureExt};
use log::{debug, info};
use nails::execution::ExitCode;
use shell_quote::bash;
use store::{OneOffStoreFileByDigest, Snapshot, Store, StoreError};
use task_executor::Executor;
use tempfile::TempDir;
use tokio::process::Command;
use tokio::sync::RwLock;
use tokio::time::{timeout, Duration};
use tokio_util::codec::{BytesCodec, FramedRead};
use workunit_store::{in_workunit, Level, Metric, RunningWorkunit};

use crate::{
    Context, FallibleProcessResultWithPlatform, ImmutableInputs, ManagedChild, NamedCaches,
    Platform, Process, ProcessError, ProcessResultMetadata, ProcessResultSource,
};

pub const USER_EXECUTABLE_MODE: u32 = 0o100755;

#[derive(Clone, Copy, Debug, PartialEq, Eq, strum_macros::EnumString)]
#[strum(serialize_all = "snake_case")]
pub enum KeepSandboxes {
    Always,
    Never,
    OnFailure,
}

pub struct CommandRunner {
    pub store: Store,
    executor: Executor,
    work_dir_base: PathBuf,
    named_caches: NamedCaches,
    immutable_inputs: ImmutableInputs,
    keep_sandboxes: KeepSandboxes,
    platform: Platform,
    spawn_lock: RwLock<()>,
}

impl CommandRunner {
    pub fn new(
        store: Store,
        executor: Executor,
        work_dir_base: PathBuf,
        named_caches: NamedCaches,
        immutable_inputs: ImmutableInputs,
        keep_sandboxes: KeepSandboxes,
    ) -> CommandRunner {
        CommandRunner {
            store,
            executor,
            work_dir_base,
            named_caches,
            immutable_inputs,
            keep_sandboxes,
            platform: Platform::current().unwrap(),
            spawn_lock: RwLock::new(()),
        }
    }

    fn platform(&self) -> Platform {
        self.platform
    }

    async fn construct_output_snapshot(
        store: Store,
        posix_fs: Arc<fs::PosixFS>,
        output_file_paths: BTreeSet<RelativePath>,
        output_dir_paths: BTreeSet<RelativePath>,
    ) -> Result<Snapshot, String> {
        let output_paths = output_dir_paths
            .into_iter()
            .flat_map(|p| {
                let mut dir_glob = {
                    let mut dir = PathBuf::from(p).into_os_string();
                    if dir.is_empty() {
                        dir.push(".")
                    }
                    dir
                };
                let dir = dir_glob.clone();
                dir_glob.push("/**");
                vec![dir, dir_glob]
            })
            .chain(
                output_file_paths
                    .into_iter()
                    .map(|p| PathBuf::from(p).into_os_string()),
            )
            .map(|s| {
                s.into_string()
                    .map_err(|e| format!("Error stringifying output paths: {:?}", e))
            })
            .collect::<Result<Vec<_>, _>>()?;

        // TODO: should we error when globs fail?
        let output_globs = PathGlobs::new(
            output_paths,
            StrictGlobMatching::Ignore,
            GlobExpansionConjunction::AllMatch,
        )
        .parse()?;

        let path_stats = posix_fs
            .expand_globs(output_globs, None)
            .map_err(|err| format!("Error expanding output globs: {}", err))
            .await?;
        Snapshot::from_path_stats(
            OneOffStoreFileByDigest::new(store, posix_fs, true),
            path_stats,
        )
        .await
    }

    pub fn named_caches(&self) -> &NamedCaches {
        &self.named_caches
    }

    pub fn immutable_inputs(&self) -> &ImmutableInputs {
        &self.immutable_inputs
    }
}

impl Debug for CommandRunner {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("local::CommandRunner")
            .finish_non_exhaustive()
    }
}

// TODO: A Stream that ends with `Exit` is error prone: we should consider creating a Child struct
// similar to nails::server::Child (which is itself shaped like `std::process::Child`).
// See https://github.com/stuhood/nails/issues/1 for more info.
#[derive(Debug, PartialEq, Eq)]
pub enum ChildOutput {
    Stdout(Bytes),
    Stderr(Bytes),
    Exit(ExitCode),
}

///
/// Collect the outputs of a child process.
///
async fn collect_child_outputs<'a>(
    stdout: &'a mut BytesMut,
    stderr: &'a mut BytesMut,
    mut stream: BoxStream<'static, Result<ChildOutput, String>>,
) -> Result<i32, String> {
    let mut exit_code = 1;

    while let Some(child_output_res) = stream.next().await {
        match child_output_res? {
            ChildOutput::Stdout(bytes) => stdout.extend_from_slice(&bytes),
            ChildOutput::Stderr(bytes) => stderr.extend_from_slice(&bytes),
            ChildOutput::Exit(code) => exit_code = code.0,
        };
    }

    Ok(exit_code)
}

#[async_trait]
impl super::CommandRunner for CommandRunner {
    ///
    /// Runs a command on this machine in the passed working directory.
    ///
    async fn run(
        &self,
        context: Context,
        _workunit: &mut RunningWorkunit,
        req: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
        let req_debug_repr = format!("{:#?}", req);
        in_workunit!(
            "run_local_process",
            req.level,
            // NB: See engine::nodes::NodeKey::workunit_level for more information on why this workunit
            // renders at the Process's level.
            desc = Some(req.description.clone()),
            |workunit| async move {
                let mut workdir = create_sandbox(
                    self.executor.clone(),
                    &self.work_dir_base,
                    &req.description,
                    self.keep_sandboxes,
                )?;

                // Start working on a mutable version of the process.
                let mut req = req;
                // Update env, replacing `{chroot}` placeholders with `workdir_path`.
                apply_chroot(workdir.path().to_str().unwrap(), &mut req);

                // Prepare the workdir.
                let exclusive_spawn = prepare_workdir(
                    workdir.path().to_owned(),
                    &req,
                    req.input_digests.input_files.clone(),
                    self.store.clone(),
                    self.executor.clone(),
                    &self.named_caches,
                    &self.immutable_inputs,
                )
                .await?;

                workunit.increment_counter(Metric::LocalExecutionRequests, 1);
                // NB: The constraint on `CapturedWorkdir` is that any child processes spawned here have
                // exited (or been killed in their `Drop` handlers), so this function can rely on the usual
                // Drop order of local variables to assume that the sandbox is cleaned up after the process
                // is.
                let res = self
                    .run_and_capture_workdir(
                        req.clone(),
                        context,
                        self.store.clone(),
                        self.executor.clone(),
                        workdir.path().to_owned(),
                        (),
                        exclusive_spawn,
                        self.platform(),
                    )
                    .map_err(|msg| {
                        // Processes that experience no infrastructure issues should result in an "Ok" return,
                        // potentially with an exit code that indicates that they failed (with more information
                        // on stderr). Actually failing at this level indicates a failure to start or otherwise
                        // interact with the process, which would generally be an infrastructure or implementation
                        // error (something missing from the sandbox, incorrect permissions, etc).
                        //
                        // Given that this is expected to be rare, we dump the entire process definition in the
                        // error.
                        ProcessError::Unclassified(format!(
                            "Failed to execute: {}\n\n{}",
                            req_debug_repr, msg
                        ))
                    })
                    .await;

                if self.keep_sandboxes == KeepSandboxes::Always
                    || self.keep_sandboxes == KeepSandboxes::OnFailure
                        && res.as_ref().map(|r| r.exit_code).unwrap_or(1) != 0
                {
                    workdir.keep(&req.description);
                    setup_run_sh_script(
                        &req.env,
                        &req.working_directory,
                        &req.argv,
                        workdir.path(),
                    )?;
                }

                res
            }
        )
        .await
    }
}

#[async_trait]
impl CapturedWorkdir for CommandRunner {
    type WorkdirToken = ();

    async fn run_in_workdir<'a, 'b, 'c>(
        &'a self,
        workdir_path: &'b Path,
        _workdir_token: (),
        req: Process,
        exclusive_spawn: bool,
    ) -> Result<BoxStream<'c, Result<ChildOutput, String>>, String> {
        let cwd = if let Some(ref working_directory) = req.working_directory {
            workdir_path.join(working_directory)
        } else {
            workdir_path.to_owned()
        };
        let mut command = Command::new(&req.argv[0]);
        command
            .env_clear()
            // It would be really nice not to have to manually set PATH but this is sadly the only way
            // to stop automatic PATH searching.
            .env("PATH", "")
            .args(&req.argv[1..])
            .current_dir(cwd)
            .envs(&req.env)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // See the documentation of the `CapturedWorkdir::run_in_workdir` method, but `exclusive_spawn`
        // indicates the binary we're spawning was written out by the current thread, and, as such,
        // there may be open file handles against it. This will occur whenever a concurrent call of this
        // method proceeds through its fork point
        // (https://pubs.opengroup.org/onlinepubs/009695399/functions/fork.html) while the current
        // thread is in the middle of writing the binary and thus captures a clone of the open file
        // handle, but that concurrent call has not yet gotten to its exec point
        // (https://pubs.opengroup.org/onlinepubs/009695399/functions/exec.html) where the operating
        // system will close the cloned file handle (via O_CLOEXEC being set on all files opened by
        // Rust). To prevent a race like this holding this thread's binary open leading to an ETXTBSY
        // (https://pubs.opengroup.org/onlinepubs/9699919799/functions/V2_chap02.html) error, we
        // maintain RwLock that allows non-`exclusive_spawn` binaries to spawn concurrently but ensures
        // all such concurrent spawns have completed (and thus closed any cloned file handles) before
        // proceeding to spawn the `exclusive_spawn` binary this thread has written.
        //
        // See: https://github.com/golang/go/issues/22315 for an excellent description of this generic
        // unix problem.
        let mut fork_exec = move || ManagedChild::spawn(&mut command, None);
        let mut child = {
            if exclusive_spawn {
                let _write_locked = self.spawn_lock.write().await;

                // Despite the mitigations taken against racing our own forks, forks can happen in our
                // process but outside of our control (in libraries). As such, we back-stop by sleeping and
                // trying again for a while if we do hit one of these fork races we do not control.
                const MAX_ETXTBSY_WAIT: Duration = Duration::from_millis(100);
                let mut retries: u32 = 0;
                let mut sleep_millis = 1;

                let start_time = std::time::Instant::now();
                loop {
                    match fork_exec() {
                        Err(e) => {
                            if e.raw_os_error() == Some(libc::ETXTBSY)
                                && start_time.elapsed() < MAX_ETXTBSY_WAIT
                            {
                                tokio::time::sleep(std::time::Duration::from_millis(sleep_millis))
                                    .await;
                                retries += 1;
                                sleep_millis *= 2;
                                continue;
                            } else if retries > 0 {
                                break Err(format!(
                  "Error launching process after {} {} for ETXTBSY. Final error was: {:?}",
                  retries,
                  if retries == 1 { "retry" } else { "retries" },
                  e
                ));
                            } else {
                                break Err(format!("Error launching process: {:?}", e));
                            }
                        }
                        Ok(child) => break Ok(child),
                    }
                }
            } else {
                let _read_locked = self.spawn_lock.read().await;
                fork_exec().map_err(|e| format!("Error launching process: {:?}", e))
            }
        }?;

        debug!("spawned local process as {:?} for {:?}", child.id(), req);
        let stdout_stream = FramedRead::new(child.stdout.take().unwrap(), BytesCodec::new())
            .map_ok(|bytes| ChildOutput::Stdout(bytes.into()))
            .fuse()
            .boxed();
        let stderr_stream = FramedRead::new(child.stderr.take().unwrap(), BytesCodec::new())
            .map_ok(|bytes| ChildOutput::Stderr(bytes.into()))
            .fuse()
            .boxed();
        let exit_stream = async move {
            child
                .wait()
                .map_ok(|exit_status| {
                    ChildOutput::Exit(ExitCode(
                        exit_status
                            .code()
                            .or_else(|| exit_status.signal().map(Neg::neg))
                            .expect("Child process should exit via returned code or signal."),
                    ))
                })
                .await
        }
        .into_stream()
        .boxed();
        let result_stream =
            futures::stream::select_all(vec![stdout_stream, stderr_stream, exit_stream]);

        Ok(result_stream
            .map_err(|e| format!("Failed to consume process outputs: {:?}", e))
            .boxed())
    }
}

#[async_trait]
pub trait CapturedWorkdir {
    type WorkdirToken: Send;

    async fn run_and_capture_workdir(
        &self,
        req: Process,
        context: Context,
        store: Store,
        executor: Executor,
        workdir_path: PathBuf,
        workdir_token: Self::WorkdirToken,
        exclusive_spawn: bool,
        platform: Platform,
    ) -> Result<FallibleProcessResultWithPlatform, String> {
        let start_time = Instant::now();
        let mut stdout = BytesMut::with_capacity(8192);
        let mut stderr = BytesMut::with_capacity(8192);

        // Spawn the process.
        // NB: We fully buffer the `Stream` into the stdout/stderr buffers, but the idea going forward
        // is that we eventually want to pass incremental results on down the line for streaming
        // process results to console logs, etc.
        let exit_code_result = {
            let exit_code_future = collect_child_outputs(
                &mut stdout,
                &mut stderr,
                self.run_in_workdir(&workdir_path, workdir_token, req.clone(), exclusive_spawn)
                    .await?,
            );
            if let Some(req_timeout) = req.timeout {
                timeout(req_timeout, exit_code_future)
                    .await
                    .map_err(|e| e.to_string())
                    .and_then(|r| r)
            } else {
                exit_code_future.await
            }
        };

        // Capture the process outputs.
        let output_snapshot = if req.output_files.is_empty() && req.output_directories.is_empty() {
            store::Snapshot::empty()
        } else {
            let root = if let Some(ref working_directory) = req.working_directory {
                workdir_path.join(working_directory)
            } else {
                workdir_path.clone()
            };
            // Use no ignore patterns, because we are looking for explicitly listed paths.
            let posix_fs = Arc::new(
                fs::PosixFS::new(root, fs::GitignoreStyleExcludes::empty(), executor.clone())
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
            .await?
        };

        let elapsed = start_time.elapsed();
        let result_metadata = ProcessResultMetadata::new(
            Some(elapsed.into()),
            ProcessResultSource::RanLocally,
            context.run_id,
        );

        match exit_code_result {
            Ok(exit_code) => {
                let (stdout_digest, stderr_digest) = try_join!(
                    store.store_file_bytes(stdout.into(), true),
                    store.store_file_bytes(stderr.into(), true),
                )?;
                Ok(FallibleProcessResultWithPlatform {
                    stdout_digest,
                    stderr_digest,
                    exit_code,
                    output_directory: output_snapshot.into(),
                    platform,
                    metadata: result_metadata,
                })
            }
            Err(msg) if msg == "deadline has elapsed" => {
                stderr.extend_from_slice(
                    format!(
                        "\n\nExceeded timeout of {:.1} seconds when executing local process: {}",
                        req.timeout.map(|dur| dur.as_secs_f32()).unwrap_or(-1.0),
                        req.description
                    )
                    .as_bytes(),
                );

                let (stdout_digest, stderr_digest) = try_join!(
                    store.store_file_bytes(stdout.into(), true),
                    store.store_file_bytes(stderr.into(), true),
                )?;

                Ok(FallibleProcessResultWithPlatform {
                    stdout_digest,
                    stderr_digest,
                    exit_code: -libc::SIGTERM,
                    output_directory: EMPTY_DIRECTORY_DIGEST.clone(),
                    platform,
                    metadata: result_metadata,
                })
            }
            Err(msg) => Err(msg),
        }
    }

    ///
    /// Spawn the given process in a working directory prepared with its expected input digest.
    ///
    /// NB: The implementer of this method must guarantee that the spawned process has completely
    /// exited when the returned BoxStream is Dropped. Otherwise it might be possible for the process
    /// to observe the working directory that it is running in being torn down. In most cases, this
    /// requires Drop handlers to synchronously wait for their child processes to exit.
    ///
    /// If the process to be executed has an `argv[0]` that points into its input digest then
    /// `exclusive_spawn` will be `true` and the spawn implementation should account for the
    /// possibility of concurrent fork+exec holding open the cloned `argv[0]` file descriptor, which,
    /// if unhandled, will result in ETXTBSY errors spawning the process.
    ///
    /// See the documentation note in `CommandRunner` in this file for more details.
    ///
    /// TODO(John Sirois): https://github.com/pantsbuild/pants/issues/10601
    ///  Centralize local spawning to one object - we currently spawn here (in
    ///  process_execution::local::CommandRunner) to launch user `Process`es and in
    ///  process_execution::nailgun::CommandRunner when a jvm nailgun server needs to be started. The
    ///  proper handling of `exclusive_spawn` really requires a single point of control for all
    ///  fork+execs in the scheduler. For now we rely on the fact that the process_execution::nailgun
    ///  module is dead code in practice.
    ///
    async fn run_in_workdir<'a, 'b, 'c>(
        &'a self,
        workdir_path: &'b Path,
        workdir_token: Self::WorkdirToken,
        req: Process,
        exclusive_spawn: bool,
    ) -> Result<BoxStream<'c, Result<ChildOutput, String>>, String>;
}

///
/// Mutates a Process, replacing any `{chroot}` placeholders with `chroot_path`.
///
pub fn apply_chroot(chroot_path: &str, req: &mut Process) {
    for value in req.env.values_mut() {
        if value.contains("{chroot}") {
            *value = value.replace("{chroot}", chroot_path);
        }
    }
    for value in &mut req.argv {
        if value.contains("{chroot}") {
            *value = value.replace("{chroot}", chroot_path);
        }
    }
}

/// Prepares the given workdir for use by the given Process.
///
/// Returns true if the executable for the Process was created in the workdir, indicating that
/// `exclusive_spawn` is required.
///
/// TODO: Both the symlinks for named_caches/immutable_inputs and the empty output directories
/// required by the spec should be created via a synthetic Digest containing SymlinkNodes and
/// the empty output directories. That would:
///   1. improve validation that nothing we create collides.
///   2. allow for materialization to safely occur fully in parallel, rather than partially
///      synchronously in the background.
///
pub async fn prepare_workdir(
    workdir_path: PathBuf,
    req: &Process,
    materialized_input_digest: DirectoryDigest,
    store: Store,
    executor: Executor,
    named_caches: &NamedCaches,
    immutable_inputs: &ImmutableInputs,
) -> Result<bool, StoreError> {
    // Collect the symlinks to create for immutable inputs or named caches.
    let workdir_symlinks = immutable_inputs
        .local_paths(&req.input_digests.immutable_inputs)
        .await?
        .into_iter()
        .chain(named_caches.local_paths(&req.append_only_caches))
        .collect::<Vec<_>>();

    // Capture argv0 as the executable path so that we can test whether we have created it in the
    // sandbox.
    let maybe_executable_path = {
        let mut executable_path = PathBuf::from(&req.argv[0]);
        if executable_path.is_relative() {
            if let Some(working_directory) = &req.working_directory {
                executable_path = working_directory.as_ref().join(executable_path)
            }
            Some(executable_path)
        } else {
            None
        }
    };

    // Start with async materialization of input snapshots, followed by synchronous materialization
    // of other configured inputs. Note that we don't do this in parallel, as that might cause
    // non-determinism when paths overlap: see the method doc.
    let store2 = store.clone();
    let workdir_path_2 = workdir_path.clone();
    in_workunit!("setup_sandbox", Level::Debug, |_workunit| async move {
        store2
            .materialize_directory(
                workdir_path_2,
                materialized_input_digest,
                Permissions::Writable,
            )
            .await
    })
    .await?;

    let workdir_path2 = workdir_path.clone();
    let output_file_paths = req.output_files.clone();
    let output_dir_paths = req.output_directories.clone();
    let maybe_jdk_home = req.jdk_home.clone();
    let exclusive_spawn = executor
        .spawn_blocking(move || {
            if let Some(jdk_home) = maybe_jdk_home {
                symlink(jdk_home, workdir_path2.join(".jdk")).map_err(|err| {
                    format!("Error making JDK symlink for local execution: {:?}", err)
                })?
            }

            // The bazel remote execution API specifies that the parent directories for output files and
            // output directories should be created before execution completes: see the method doc.
            let parent_paths_to_create: HashSet<_> = output_file_paths
                .iter()
                .chain(output_dir_paths.iter())
                .map(|relative_path| relative_path.as_ref())
                .chain(workdir_symlinks.iter().map(|s| s.src.as_path()))
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

            for workdir_symlink in workdir_symlinks {
                // TODO: Move initialization of the dst directory into NamedCaches.
                safe_create_dir_all_ioerror(&workdir_symlink.dst).map_err(|err| {
                    format!(
                        "Error making {} for local execution: {:?}",
                        workdir_symlink.dst.display(),
                        err
                    )
                })?;
                let src = workdir_path2.join(&workdir_symlink.src);
                symlink(&workdir_symlink.dst, &src).map_err(|err| {
                    format!(
                        "Error linking {} -> {} for local execution: {:?}",
                        src.display(),
                        workdir_symlink.dst.display(),
                        err
                    )
                })?;
            }

            let exe_was_materialized = maybe_executable_path
                .as_ref()
                .map_or(false, |p| workdir_path2.join(&p).exists());
            if exe_was_materialized {
                debug!(
                    "Obtaining exclusive spawn lock for process since \
               we materialized its executable {:?}.",
                    maybe_executable_path
                );
            }
            let res: Result<_, String> = Ok(exe_was_materialized);
            res
        })
        .await?;
    Ok(exclusive_spawn)
}

///
/// Creates an optionally-cleaned-up sandbox in the given base path.
///
/// If KeepSandboxes::Always, it is immediately marked preserved: otherwise, the caller should
/// decide whether to preserve it.
///
pub fn create_sandbox(
    executor: Executor,
    base_directory: &Path,
    description: &str,
    keep_sandboxes: KeepSandboxes,
) -> Result<AsyncDropSandbox, String> {
    let workdir = tempfile::Builder::new()
        .prefix("pants-sandbox-")
        .tempdir_in(base_directory)
        .map_err(|err| {
            format!(
                "Error making tempdir for local process execution: {:?}",
                err
            )
        })?;

    let mut sandbox = AsyncDropSandbox(executor, workdir.path().to_owned(), Some(workdir));
    if keep_sandboxes == KeepSandboxes::Always {
        sandbox.keep(description);
    }
    Ok(sandbox)
}

/// Dropping sandboxes can involve a lot of IO, so it is spawned to the background as a blocking
/// task.
#[must_use]
pub struct AsyncDropSandbox(Executor, PathBuf, Option<TempDir>);

impl AsyncDropSandbox {
    pub fn path(&self) -> &Path {
        &self.1
    }

    ///
    /// Consume the `TempDir` without deleting directory on the filesystem, meaning that the
    /// temporary directory will no longer be automatically deleted when dropped.
    ///
    pub fn keep(&mut self, description: &str) {
        if let Some(workdir) = self.2.take() {
            let preserved_path = workdir.into_path();
            info!(
                "Preserving local process execution dir {} for {}",
                preserved_path.display(),
                description,
            );
        }
    }
}

impl Drop for AsyncDropSandbox {
    fn drop(&mut self) {
        if let Some(sandbox) = self.2.take() {
            let _background_cleanup = self.0.spawn_blocking(|| std::mem::drop(sandbox));
        }
    }
}

/// Create a file called __run.sh with the env, cwd and argv used by Pants to facilitate debugging.
fn setup_run_sh_script(
    env: &BTreeMap<String, String>,
    working_directory: &Option<RelativePath>,
    argv: &[String],
    workdir_path: &Path,
) -> Result<(), String> {
    let mut env_var_strings: Vec<String> = vec![];
    for (key, value) in env.iter() {
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
    for arg in argv.iter() {
        let quoted_arg = bash::escape(&arg);
        let arg_str = str::from_utf8(&quoted_arg)
            .map_err(|e| format!("{:?}", e))?
            .to_string();
        full_command_line.push(arg_str);
    }

    let stringified_cwd = {
        let cwd = if let Some(ref working_directory) = working_directory {
            workdir_path.join(working_directory)
        } else {
            workdir_path.to_owned()
        };
        let quoted_cwd = bash::escape(&cwd);
        str::from_utf8(&quoted_cwd)
            .map_err(|e| format!("{:?}", e))?
            .to_string()
    };

    let stringified_command_line: String = full_command_line.join(" ");
    let full_script = format!(
        "#!/bin/bash
# This command line should execute the same process as pants did internally.
export {}
cd {}
{}
",
        stringified_env_vars, stringified_cwd, stringified_command_line,
    );

    let full_file_path = workdir_path.join("__run.sh");

    std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(USER_EXECUTABLE_MODE) // Executable for user, read-only for others.
        .open(&full_file_path)
        .map_err(|e| format!("{:?}", e))?
        .write_all(full_script.as_bytes())
        .map_err(|e| format!("{:?}", e))
}
