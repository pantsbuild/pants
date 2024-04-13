// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ops::Neg;
use std::os::unix::process::ExitStatusExt;
use std::sync::Arc;
use std::{
    fmt,
    path::{Path, PathBuf},
    process::Stdio,
};

use async_trait::async_trait;
use futures::stream::BoxStream;
use futures::{FutureExt, StreamExt, TryFutureExt, TryStreamExt};
use log::debug;
use nails::execution::ExitCode;
use store::{ImmutableInputs, Store};
use task_executor::Executor;
use tokio::process::Command;
use tokio::sync::RwLock;
use tokio_util::codec::{BytesCodec, FramedRead};
use workunit_store::RunningWorkunit;

use crate::fork_exec::spawn_process;
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
    spawn_lock: Arc<RwLock<()>>,
}

impl CommandRunner {
    pub fn new(
        store: Store,
        executor: Executor,
        build_root: PathBuf,
        work_dir_base: PathBuf,
        named_caches: NamedCaches,
        immutable_inputs: ImmutableInputs,
        spawn_lock: Arc<RwLock<()>>,
    ) -> Self {
        Self {
            store,
            executor,
            build_root,
            work_dir_base,
            named_caches,
            immutable_inputs,
            spawn_lock,
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

        self.run_and_capture_workdir(
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

        let mut child = spawn_process(self.spawn_lock.clone(), exclusive_spawn, move || {
            ManagedChild::spawn(&mut command, None)
        })
        .await?;

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
