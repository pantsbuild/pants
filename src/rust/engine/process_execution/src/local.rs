// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fmt::{self, Debug};
use std::io::Write;
use std::ops::Neg;
use std::os::unix::{fs::OpenOptionsExt, process::ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::str;
use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;
use bytes::{Bytes, BytesMut};
use fs::{
    self, DigestTrie, DirectoryDigest, GlobExpansionConjunction, GlobMatching, PathGlobs,
    Permissions, RelativePath, StrictGlobMatching, SymlinkBehavior, TypedPath,
    EMPTY_DIRECTORY_DIGEST,
};
use futures::stream::{BoxStream, StreamExt, TryStreamExt};
use futures::{try_join, FutureExt, TryFutureExt};
use log::{debug, info};
use nails::execution::ExitCode;
use shell_quote::bash;
use store::{
    ImmutableInputs, OneOffStoreFileByDigest, Snapshot, SnapshotOps, Store, StoreError,
    WorkdirSymlink,
};
use task_executor::Executor;
use tempfile::TempDir;
use tokio::process::Command;
use tokio::sync::RwLock;
use tokio::time::{timeout, Duration};
use tokio_util::codec::{BytesCodec, FramedRead};
use workunit_store::{in_workunit, Level, Metric, RunningWorkunit};

use crate::{
    Context, FallibleProcessResultWithPlatform, ManagedChild, NamedCaches, Process, ProcessError,
    ProcessResultMetadata, ProcessResultSource,
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
            spawn_lock: RwLock::new(()),
        }
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
                    .map_err(|e| format!("Error stringifying output paths: {e:?}"))
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
            .expand_globs(output_globs, SymlinkBehavior::Aware, None)
            .map_err(|err| format!("Error expanding output globs: {err}"))
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
pub async fn collect_child_outputs<'a, 'b>(
    stdout: &'a mut BytesMut,
    stderr: &'a mut BytesMut,
    mut stream: BoxStream<'b, Result<ChildOutput, String>>,
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
        let req_debug_repr = format!("{req:#?}");
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
                    &self.work_dir_base,
                    &req,
                    req.input_digests.inputs.clone(),
                    &self.store,
                    &self.named_caches,
                    &self.immutable_inputs,
                    None,
                    None,
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
                            "Failed to execute: {req_debug_repr}\n\n{msg}"
                        ))
                    })
                    .await;

                if self.keep_sandboxes == KeepSandboxes::Always
                    || self.keep_sandboxes == KeepSandboxes::OnFailure
                        && res.as_ref().map(|r| r.exit_code).unwrap_or(1) != 0
                {
                    workdir.keep(&req.description);
                    setup_run_sh_script(
                        workdir.path(),
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

    async fn shutdown(&self) -> Result<(), String> {
        Ok(())
    }
}

#[async_trait]
impl CapturedWorkdir for CommandRunner {
    type WorkdirToken = ();

    async fn run_in_workdir<'s, 'c, 'w, 'r>(
        &'s self,
        _context: &'c Context,
        workdir_path: &'w Path,
        _workdir_token: (),
        req: Process,
        exclusive_spawn: bool,
    ) -> Result<BoxStream<'r, Result<ChildOutput, String>>, String> {
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
                                break Err(format!("Error launching process: {e:?}"));
                            }
                        }
                        Ok(child) => break Ok(child),
                    }
                }
            } else {
                let _read_locked = self.spawn_lock.read().await;
                fork_exec().map_err(|e| format!("Error launching process: {e:?}"))
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
            .map_err(|e| format!("Failed to consume process outputs: {e:?}"))
            .boxed())
    }
}

#[async_trait]
pub trait CapturedWorkdir {
    type WorkdirToken: Clone + Send;

    async fn run_and_capture_workdir(
        &self,
        req: Process,
        context: Context,
        store: Store,
        executor: Executor,
        workdir_path: PathBuf,
        workdir_token: Self::WorkdirToken,
        exclusive_spawn: bool,
    ) -> Result<FallibleProcessResultWithPlatform, String> {
        let start_time = Instant::now();
        let mut stdout = BytesMut::with_capacity(8192);
        let mut stderr = BytesMut::with_capacity(8192);

        // Spawn the process.
        // NB: We fully buffer the `Stream` into the stdout/stderr buffers, but the idea going forward
        // is that we eventually want to pass incremental results on down the line for streaming
        // process results to console logs, etc.
        let exit_code_result = {
            let workdir_token = workdir_token.clone();
            let exit_code_future = collect_child_outputs(
                &mut stdout,
                &mut stderr,
                self.run_in_workdir(
                    &context,
                    &workdir_path,
                    workdir_token,
                    req.clone(),
                    exclusive_spawn,
                )
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
        self.prepare_workdir_for_capture(&context, &workdir_path, workdir_token, &req)
            .await?;
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
        fs::PosixFS::new(root, fs::GitignoreStyleExcludes::empty(), executor.clone()).map_err(
          |err| {
            format!("Error making posix_fs to fetch local process execution output files: {err}")
          },
        )?,
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
            ProcessResultSource::Ran,
            req.execution_environment,
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
    /// TODO(John Sirois): <https://github.com/pantsbuild/pants/issues/10601>
    ///  Centralize local spawning to one object - we currently spawn here (in
    ///  process_execution::local::CommandRunner) to launch user `Process`es and in
    ///  process_execution::nailgun::CommandRunner when a jvm nailgun server needs to be started. The
    ///  proper handling of `exclusive_spawn` really requires a single point of control for all
    ///  fork+execs in the scheduler. For now we rely on the fact that the process_execution::nailgun
    ///  module is dead code in practice.
    ///
    async fn run_in_workdir<'s, 'c, 'w, 'r>(
        &'s self,
        context: &'c Context,
        workdir_path: &'w Path,
        workdir_token: Self::WorkdirToken,
        req: Process,
        exclusive_spawn: bool,
    ) -> Result<BoxStream<'r, Result<ChildOutput, String>>, String>;

    ///
    /// An optionally-implemented method which is called after the child process has completed, but
    /// before capturing the sandbox. The default implementation does nothing.
    ///
    async fn prepare_workdir_for_capture(
        &self,
        _context: &Context,
        _workdir_path: &Path,
        _workdir_token: Self::WorkdirToken,
        _req: &Process,
    ) -> Result<(), String> {
        Ok(())
    }
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

/// Creates a Digest for the entire input sandbox contents of the given Process, including absolute
/// symlinks to immutable inputs, named caches, and JDKs (if configured).
pub async fn prepare_workdir_digest(
    req: &Process,
    input_digest: DirectoryDigest,
    store: &Store,
    named_caches: &NamedCaches,
    immutable_inputs: Option<&ImmutableInputs>,
    named_caches_prefix: Option<&Path>,
    immutable_inputs_prefix: Option<&Path>,
) -> Result<DirectoryDigest, StoreError> {
    let mut paths = Vec::new();

    // Symlinks for immutable inputs and named caches.
    let mut workdir_symlinks = Vec::new();
    {
        if let Some(immutable_inputs) = immutable_inputs {
            let symlinks = immutable_inputs
                .local_paths(&req.input_digests.immutable_inputs)
                .await?;

            match immutable_inputs_prefix {
                Some(prefix) => workdir_symlinks.extend(symlinks.into_iter().map(|symlink| {
                    WorkdirSymlink {
                        src: symlink.src,
                        dst: prefix.join(
                            symlink
                                .dst
                                .strip_prefix(immutable_inputs.workdir())
                                .unwrap(),
                        ),
                    }
                })),
                None => workdir_symlinks.extend(symlinks),
            }
        }

        let symlinks = named_caches
            .paths(&req.append_only_caches)
            .await
            .map_err(|err| {
                StoreError::Unclassified(format!(
                    "Failed to make named cache(s) for local execution: {err:?}"
                ))
            })?;
        match named_caches_prefix {
            Some(prefix) => {
                workdir_symlinks.extend(symlinks.into_iter().map(|symlink| WorkdirSymlink {
                    src: symlink.src,
                    dst: prefix.join(symlink.dst.strip_prefix(named_caches.base_path()).unwrap()),
                }))
            }
            None => workdir_symlinks.extend(symlinks),
        }
    }
    paths.extend(workdir_symlinks.iter().map(|symlink| TypedPath::Link {
        path: &symlink.src,
        target: &symlink.dst,
    }));

    // Symlink for JDK.
    if let Some(jdk_home) = &req.jdk_home {
        paths.push(TypedPath::Link {
            path: Path::new(".jdk"),
            target: jdk_home,
        });
    }

    // The bazel remote execution API specifies that the parent directories for output files and
    // output directories should be created before execution completes.
    let parent_paths_to_create: HashSet<_> = req
        .output_files
        .iter()
        .chain(req.output_directories.iter())
        .filter_map(|rel_path| rel_path.as_ref().parent())
        .filter(|parent| !parent.as_os_str().is_empty())
        .collect();
    paths.extend(parent_paths_to_create.into_iter().map(TypedPath::Dir));

    // Finally, create a tree for all of the additional paths, and merge it with the input
    // Digest.
    let additions = DigestTrie::from_unique_paths(paths, &HashMap::new())?;

    store.merge(vec![input_digest, additions.into()]).await
}

/// Prepares the given workdir for use by the given Process.
///
/// Returns true if the executable for the Process was created in the workdir, indicating that
/// `exclusive_spawn` is required.
///
pub async fn prepare_workdir(
    workdir_path: PathBuf,
    workdir_root_path: &Path,
    req: &Process,
    materialized_input_digest: DirectoryDigest,
    store: &Store,
    named_caches: &NamedCaches,
    immutable_inputs: &ImmutableInputs,
    named_caches_prefix: Option<&Path>,
    immutable_inputs_prefix: Option<&Path>,
) -> Result<bool, StoreError> {
    // Capture argv0 as the executable path so that we can test whether we have created it in the
    // sandbox.
    let maybe_executable_path = {
        let mut executable_path = PathBuf::from(&req.argv[0]);
        if executable_path.is_relative() {
            if let Some(working_directory) = &req.working_directory {
                executable_path = working_directory.as_ref().join(executable_path)
            }
            Some(workdir_path.join(executable_path))
        } else {
            None
        }
    };

    // Prepare the digest to use, and then materialize it.
    in_workunit!("setup_sandbox", Level::Debug, |_workunit| async move {
        let complete_input_digest = prepare_workdir_digest(
            req,
            materialized_input_digest,
            store,
            named_caches,
            Some(immutable_inputs),
            named_caches_prefix,
            immutable_inputs_prefix,
        )
        .await?;

        let mut mutable_paths = req.output_files.clone();
        mutable_paths.extend(req.output_directories.clone());
        store
            .materialize_directory(
                workdir_path,
                workdir_root_path,
                complete_input_digest,
                false,
                &mutable_paths,
                Permissions::Writable,
            )
            .await?;

        if let Some(executable_path) = maybe_executable_path {
            Ok(tokio::fs::metadata(executable_path).await.is_ok())
        } else {
            Ok(false)
        }
    })
    .await
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
        .map_err(|err| format!("Error making tempdir for local process execution: {err:?}"))?;

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
            let _background_cleanup = self.0.native_spawn_blocking(|| std::mem::drop(sandbox));
        }
    }
}

/// Create a file called __run.sh with the env, cwd and argv used by Pants to facilitate debugging.
pub fn setup_run_sh_script(
    sandbox_path: &Path,
    env: &BTreeMap<String, String>,
    working_directory: &Option<RelativePath>,
    argv: &[String],
    workdir_path: &Path,
) -> Result<(), String> {
    let mut env_var_strings: Vec<String> = vec![];
    for (key, value) in env.iter() {
        let quoted_arg = bash::escape(value);
        let arg_str = str::from_utf8(&quoted_arg)
            .map_err(|e| format!("{e:?}"))?
            .to_string();
        let formatted_assignment = format!("{key}={arg_str}");
        env_var_strings.push(formatted_assignment);
    }
    let stringified_env_vars: String = env_var_strings.join(" ");

    // Shell-quote every command-line argument, as necessary.
    let mut full_command_line: Vec<String> = vec![];
    for arg in argv.iter() {
        let quoted_arg = bash::escape(arg);
        let arg_str = str::from_utf8(&quoted_arg)
            .map_err(|e| format!("{e:?}"))?
            .to_string();
        full_command_line.push(arg_str);
    }

    let stringified_cwd = {
        let cwd = if let Some(ref working_directory) = working_directory {
            workdir_path.join(working_directory)
        } else {
            workdir_path.to_owned()
        };
        let quoted_cwd = bash::escape(cwd);
        str::from_utf8(&quoted_cwd)
            .map_err(|e| format!("{e:?}"))?
            .to_string()
    };

    let stringified_command_line: String = full_command_line.join(" ");
    let full_script = format!(
        "#!/usr/bin/env bash
# This command line should execute the same process as pants did internally.
cd {stringified_cwd}
env -i {stringified_env_vars} {stringified_command_line}
",
    );

    let full_file_path = sandbox_path.join("__run.sh");

    std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(USER_EXECUTABLE_MODE) // Executable for user, read-only for others.
        .open(full_file_path)
        .map_err(|e| format!("{e:?}"))?
        .write_all(full_script.as_bytes())
        .map_err(|e| format!("{e:?}"))
}
