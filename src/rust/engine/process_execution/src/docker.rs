use std::fmt;
use std::path::{Path, PathBuf};

use async_trait::async_trait;
use bollard::container::LogOutput;
use bollard::Docker;
use futures::stream::BoxStream;
use futures::{StreamExt, TryFutureExt};
use nails::execution::ExitCode;
use store::Store;
use task_executor::Executor;
use workunit_store::{in_workunit, RunningWorkunit};

use crate::local::{
  apply_chroot, create_sandbox, prepare_workdir, setup_run_sh_script, CapturedWorkdir, ChildOutput,
  KeepSandboxes,
};
use crate::{
  Context, FallibleProcessResultWithPlatform, ImmutableInputs, LocalCommandRunner, NamedCaches,
  Platform, Process, ProcessError,
};

/// `CommandRunner` executes processes using a local Docker client.
pub struct CommandRunner {
  docker: Docker,
  store: Store,
  executor: Executor,
  work_dir_base: PathBuf,
  named_caches: NamedCaches,
  immutable_inputs: ImmutableInputs,
  keep_sandboxes: KeepSandboxes,
  image: String,
}

impl CommandRunner {
  pub fn new(
    store: Store,
    executor: Executor,
    work_dir_base: PathBuf,
    named_caches: NamedCaches,
    immutable_inputs: ImmutableInputs,
    keep_sandboxes: KeepSandboxes,
    image: String,
  ) -> Result<Self, String> {
    let docker = Docker::connect_with_local_defaults()
      .map_err(|err| format!("Failed to connect to local Docker: {err}"))?;
    Ok(CommandRunner {
      docker,
      store,
      executor,
      work_dir_base,
      named_caches,
      immutable_inputs,
      keep_sandboxes,
      image,
    })
  }
}

#[async_trait]
impl LocalCommandRunner for CommandRunner {
  fn store(&self) -> &Store {
    &self.store
  }

  fn named_caches(&self) -> &NamedCaches {
    &self.named_caches
  }

  fn immutable_inputs(&self) -> &ImmutableInputs {
    &self.immutable_inputs
  }
}

impl fmt::Debug for CommandRunner {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    f.debug_struct("docker::CommandRunner")
      .finish_non_exhaustive()
  }
}

#[async_trait]
impl super::CommandRunner for CommandRunner {
  async fn run(
    &self,
    context: Context,
    _workunit: &mut RunningWorkunit,
    req: Process,
  ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
    let req_debug_repr = format!("{:#?}", req);
    in_workunit!(
      "run_local_process_via_docker",
      req.level,
      // NB: See engine::nodes::NodeKey::workunit_level for more information on why this workunit
      // renders at the Process's level.
      desc = Some(req.description.clone()),
      |_workunit| async move {
        let mut workdir = create_sandbox(
          self.executor.clone(),
          &self.work_dir_base,
          &req.description,
          self.keep_sandboxes,
        )?;

        // Start working on a mutable version of the process.
        let mut req = req;

        // Update env, replacing `{chroot}` placeholders with `/pants-work`. This is the mount point
        // for the work directory within the Docker container.
        //
        // DOCKER-TODO: With cached containers, the destination in the container
        // will need to be unique within that container to avoid conflicts.
        apply_chroot("/pants-work", &mut req);

        // Prepare the workdir.
        // DOCKER-NOTE: The input root will be bind mounted into the container.
        let exclusive_spawn = prepare_workdir(
          workdir.path().to_owned(),
          &req,
          req.input_digests.input_files.clone(),
          self.store.clone(),
          self.executor.clone(),
          &self.named_caches,
          &self.immutable_inputs,
          Some(Path::new("/pants-named-caches")),
          Some(Path::new("/pants-immutable-inputs")),
        )
        .await?;

        // DOCKER-TODO: Add a metric for local docker execution?
        // workunit.increment_counter(Metric::LocalExecutionRequests, 1);

        let res = self
          .run_and_capture_workdir(
            req.clone(),
            context,
            self.store.clone(),
            self.executor.clone(),
            workdir.path().to_owned(),
            (
              self.immutable_inputs.workdir().to_path_buf(),
              self.named_caches.base_dir().to_path_buf(),
            ),
            exclusive_spawn,
            req
              .platform_constraint
              .unwrap_or_else(|| Platform::current().unwrap()),
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
            ProcessError::Unclassified(format!("Failed to execute: {}\n\n{}", req_debug_repr, msg))
          })
          .await;

        if self.keep_sandboxes == KeepSandboxes::Always
          || self.keep_sandboxes == KeepSandboxes::OnFailure
            && res.as_ref().map(|r| r.exit_code).unwrap_or(1) != 0
        {
          workdir.keep(&req.description);
          setup_run_sh_script(&req.env, &req.working_directory, &req.argv, workdir.path())?;
        }

        res
      }
    )
    .await
  }
}

#[async_trait]
impl CapturedWorkdir for CommandRunner {
  type WorkdirToken = (PathBuf, PathBuf);

  async fn run_in_workdir<'a, 'b, 'c>(
    &'a self,
    workdir_path: &'b Path,
    (immutable_inputs_workdir, named_caches_workdir): Self::WorkdirToken,
    req: Process,
    _exclusive_spawn: bool,
  ) -> Result<BoxStream<'c, Result<ChildOutput, String>>, String> {
    log::debug!("immutable_inputs_workdir = {:?}", &immutable_inputs_workdir);
    log::debug!("named_caches_workdir = {:?}", &named_caches_workdir);

    let env = req
      .env
      .iter()
      .map(|(key, value)| format!("{}={}", key, value))
      .collect::<Vec<_>>();

    let workdir_path_as_string = workdir_path
      .to_path_buf()
      .into_os_string()
      .into_string()
      .map_err(|s| {
        format!(
          "Unable to convert workdir_path due to non UTF-8 characters: {:?}",
          s
        )
      })?;

    let immutable_inputs_workdir_as_string = immutable_inputs_workdir
      .into_os_string()
      .into_string()
      .map_err(|s| {
        format!(
          "Unable to convert immutable_inputs_workdir due to non UTF-8 characters: {:?}",
          s
        )
      })?;

    let named_caches_workdir_as_string = named_caches_workdir
      .into_os_string()
      .into_string()
      .map_err(|s| {
        format!(
          "Unable to convert named_caches_workdir due to non UTF-8 characters: {:?}",
          s
        )
      })?;

    let working_dir = req
      .working_directory
      .map(|relpath| Path::new("/pants-work").join(&relpath))
      .unwrap_or_else(|| Path::new("/pants-work").to_path_buf())
      .into_os_string()
      .into_string()
      .map_err(|s| {
        format!(
          "Unable to convert working directory due to non UTF-8 characters: {:?}",
          s
        )
      })?;

    // DOCKER-TODO: Set creation options so we can set platform.

    let config = bollard::container::Config {
      env: Some(env),
      entrypoint: Some(req.argv),
      working_dir: Some(working_dir),
      // DOCKER-TODO: Is this necessary on linux hosts for allowing bind mount?
      // user: Some(format!("{}", unsafe { libc::geteuid() })),
      // user: Some("0".to_string()),
      host_config: Some(bollard_stubs::models::HostConfig {
        binds: Some(vec![
          format!("{}:/pants-work:rw", workdir_path_as_string),
          format!(
            "{}:/pants-immutable-inputs",
            immutable_inputs_workdir_as_string
          ),
          format!("{}:/pants-named-caches:rw", named_caches_workdir_as_string),
        ]),
        init: Some(true),
        ..bollard_stubs::models::HostConfig::default()
      }),
      image: Some(self.image.clone()),
      attach_stdout: Some(true),
      attach_stderr: Some(true),
      ..bollard::container::Config::default()
    };

    log::debug!("creating container with config: {:?}", &config);

    let container = self
      .docker
      .create_container::<&str, String>(None, config)
      .await
      .map_err(|err| format!("Failed to create Docker container: {:?}", err))?;

    log::debug!("created container {}", &container.id);

    // DOCKER-TODO: Use a drop guard to remove the container regardless of success/failure.
    // We cannot set `.host_config.auto_remove` in `config` above because containers that exit
    // early will no longer exist for purposes of attaching and capturing the output (which is
    // the entire point of this executor ...).

    self
      .docker
      .start_container::<String>(&container.id, None)
      .await
      .map_err(|err| {
        format!(
          "Failed to start Docker container `{}`: {:?}",
          &container.id, err
        )
      })?;

    log::debug!("started container {}", &container.id);

    let attach_options = bollard::container::AttachContainerOptions::<String> {
      stdout: Some(true),
      stderr: Some(true),
      logs: Some(true), // stream any output that was missed between the start_container call and now
      stream: Some(true),
      ..bollard::container::AttachContainerOptions::default()
    };

    let attach_result = self
      .docker
      .attach_container(&container.id, Some(attach_options))
      .await
      .map_err(|err| {
        format!(
          "Failed to attach to Docker container `{}`: {:?}",
          &container.id, err
        )
      })?;

    log::debug!("attached to container {}", &container.id);

    let mut output_stream = attach_result.output.boxed();

    let wait_options = bollard::container::WaitContainerOptions {
      condition: "not-running",
    };
    let mut wait_stream = self
      .docker
      .wait_container(&container.id, Some(wait_options))
      .boxed();

    let container_id = container.id.to_owned();
    let result_stream = async_stream::stream! {
      let mut run_stream = true;
      while run_stream {
        tokio::select! {
          Some(output_msg) = output_stream.next() => {
            match output_msg {
              Ok(LogOutput::StdOut { message }) => {
                log::debug!("container {} wrote {} bytes to stdout", &container_id, message.len());
                yield Ok(ChildOutput::Stdout(message));
              }
              Ok(LogOutput::StdErr { message }) => {
                log::debug!("container {} wrote {} bytes to stderr", &container_id, message.len());
                yield Ok(ChildOutput::Stderr(message));
              }
              _ => (),
            }
          }
          Some(wait_msg) = wait_stream.next() => {
            log::debug!("wait_container stream ({}): {:?}", &container_id, wait_msg);
            match wait_msg {
              Ok(r) => {
                // DOCKER-TODO: How does Docker distinguish signal versus exit code? Improve
                // `ChildResults` to better support exit code vs signal vs error message?
                let status_code = r.status_code;
                yield Ok(ChildOutput::Exit(ExitCode(status_code as i32)));
                run_stream = false;
              }
              Err(err) => {
                // DOCKER-TODO: Consider a way to pass error messages back to child status collector.
                log::error!("Docker wait failure: {:?}", err);
                yield Err(format!("Docker wait_container failure: {:?}", err));
                run_stream = false;
              }
            }
          }
        }
      }
    }
    .boxed();

    Ok(result_stream)
  }
}
