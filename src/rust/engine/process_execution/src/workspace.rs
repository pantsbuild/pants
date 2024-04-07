// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::{
    fmt,
    path::{Path, PathBuf},
    process::Stdio,
    sync::Arc,
    time::Instant,
};

use async_trait::async_trait;
use bytes::Bytes;
use store::{ImmutableInputs, Store};
use task_executor::Executor;
use workunit_store::RunningWorkunit;

use crate::{
    local::{apply_chroot, create_sandbox, prepare_workdir, KeepSandboxes},
    Context, FallibleProcessResultWithPlatform, NamedCaches, Process, ProcessError,
    ProcessResultMetadata, ProcessResultSource,
};

pub struct CommandRunner {
    store: Store,
    executor: Executor,
    build_root: PathBuf,
    work_dir_base: PathBuf,
    named_caches: NamedCaches,
    immutable_inputs: ImmutableInputs,
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
        let tempdir = create_sandbox(
            self.executor.clone(),
            &self.work_dir_base,
            "workspace process",
            KeepSandboxes::Never, // workspace execution cannot be replicated using local::CommandRunner script
        )?;

        log::debug!("tempdir = {}", tempdir.path().display());

        prepare_workdir(
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

        let p = Path::new(&req.argv[0]);
        // TODO: Deprecate this program name calculation, and recommend `{chroot}` replacement in args
        // instead.
        let program_name = p.to_path_buf();

        let mut command = tokio::process::Command::new(program_name);
        for arg in req.argv[1..].iter() {
            command.arg(arg);
        }

        // TODO: Apply the working directory to the current directory for the execution.
        command.current_dir(self.build_root.clone());

        command.env_clear();
        command.envs(&req.env);

        // TODO: Stream the output to a file (and stream to console) instead of piping in case
        // and capturin the entire output in memory.
        command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Execute the command and capture its output.
        // TODO: Stream the output to files instead of capturing entirely in memory.
        let start_time = Instant::now();
        let output = command
            .output()
            .await
            .map_err(|e| ProcessError::Unclassified(e.to_string()))?;
        let elapsed = start_time.elapsed();

        let posix_fs = Arc::new(
            fs::PosixFS::new(
                tempdir.path(),
                fs::GitignoreStyleExcludes::empty(),
                self.executor.clone(),
            )
            .map_err(|err| {
                format!(
                    "Error making posix_fs to fetch workspace process execution output files: {err}"
                )
            })?,
        );

        log::debug!("before construct_output_snapshot");

        let snapshot = crate::local::CommandRunner::construct_output_snapshot(
            self.store.clone(),
            posix_fs,
            req.output_files,
            req.output_directories,
        )
        .await?;

        log::debug!("after construct_output_snapshot");

        let output_directory = self.store.record_digest_trie(snapshot.tree, false).await?;

        let stdout_bytes = Bytes::from(output.stdout);
        let stdout_digest = self
            .store
            .store_file_bytes(stdout_bytes.clone(), false)
            .await?;

        let stderr_bytes = Bytes::from(output.stderr);
        let stderr_digest = self
            .store
            .store_file_bytes(stderr_bytes.clone(), false)
            .await?;

        let exit_code = output.status.code().unwrap_or(-1);
        log::debug!("code = {exit_code}");

        let metadata = ProcessResultMetadata::new(
            Some(elapsed.into()),
            ProcessResultSource::Ran,
            req.execution_environment,
            context.run_id,
        );

        Ok(FallibleProcessResultWithPlatform {
            stdout_digest,
            stderr_digest,
            exit_code,
            output_directory,
            metadata,
        })
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
