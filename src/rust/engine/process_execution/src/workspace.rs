// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ops::Neg;
use std::{
    fmt,
    path::{Path, PathBuf},
    process::Stdio,
    time::Duration,
};
use std::os::unix::process::ExitStatusExt;

use async_trait::async_trait;
use futures::stream::BoxStream;
use futures::{FutureExt, StreamExt, TryFutureExt, TryStreamExt};
use log::debug;
use nails::execution::ExitCode;
use store::{ImmutableInputs, Store};
use task_executor::Executor;
use tokio::process::Command;
use tokio_util::codec::{BytesCodec, FramedRead};
use workunit_store::RunningWorkunit;
use tokio::sync::RwLock;

use crate::{
    local::{
        apply_chroot, create_sandbox, prepare_workdir, CapturedWorkdir, ChildOutput, KeepSandboxes,
    },
    Context, FallibleProcessResultWithPlatform, ManagedChild, NamedCaches, Process, ProcessError,
};

pub struct CommandRunner {
    store: Store,
    executor: Executor,
    build_root: PathBuf,
    work_dir_base: PathBuf,
    named_caches: NamedCaches,
    immutable_inputs: ImmutableInputs,
    spawn_lock: RwLock<()>,
}

impl CommandRunner {
    pub fn new(
        store: Store,
        executor: Executor,
        build_root: PathBuf,
        work_dir_base: PathBuf,
        named_caches: NamedCaches,
        immutable_inputs: ImmutableInputs,
    ) -> Self {
        Self {
            store,
            executor,
            build_root,
            work_dir_base,
            named_caches,
            immutable_inputs,
            spawn_lock: RwLock::new(()),
        }
    }
}

#[async_trait]
impl super::CommandRunner for CommandRunner {
    async fn run(
        &self,
        context: Context,
        _workunit: &mut RunningWorkunit,
        mut req: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
        let req_debug_repr = format!("{req:#?}");

        let tempdir = create_sandbox(
            self.executor.clone(),
            &self.work_dir_base,
            "workspace process",
            KeepSandboxes::Never, // workspace execution cannot be replicated using local::CommandRunner script
        )?;

        log::debug!("tempdir = {}", tempdir.path().display());

        let exclusive_spawn = prepare_workdir(
            tempdir.path().to_owned(),
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

        apply_chroot(tempdir.path().to_str().unwrap(), &mut req);

        self
            .run_and_capture_workdir(
                req.clone(),
                context,
                self.store.clone(),
                self.executor.clone(),
                tempdir.path().to_owned(),
                self.build_root.clone(),
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
                ProcessError::Unclassified(format!("Failed to execute: {req_debug_repr}\n\n{msg}"))
            })
            .await
    }

    async fn shutdown(&self) -> Result<(), String> {
        Ok(())
    }
}

impl fmt::Debug for CommandRunner {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("workspace::CommandRunner")
            .finish_non_exhaustive()
    }
}

#[async_trait]
impl CapturedWorkdir for CommandRunner {
    type WorkdirToken = PathBuf;

    fn apply_working_directory_to_outputs() -> bool {
        false
    }

    async fn run_in_workdir<'s, 'c, 'w, 'r>(
        &'s self,
        _context: &'c Context,
        _workdir_path: &'w Path,
        build_root: Self::WorkdirToken,
        req: Process,
        exclusive_spawn: bool,
    ) -> Result<BoxStream<'r, Result<ChildOutput, String>>, String> {
        let cwd = if let Some(working_directory) = &req.working_directory {
            build_root.join(working_directory)
        } else {
            build_root
        };
        let mut command = Command::new(&req.argv[0]);
        command
            .env_clear()
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

        debug!(
            "spawned workspace process as {:?} for {:?}",
            child.id(),
            req
        );
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
