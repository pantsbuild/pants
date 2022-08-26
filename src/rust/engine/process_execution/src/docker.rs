use std::fmt;
use std::path::{Path, PathBuf};

use async_trait::async_trait;
use bollard::container::LogOutput;
use bollard::Docker;
use futures::stream::BoxStream;
use futures::{StreamExt, TryFutureExt, TryStreamExt};
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
  #[allow(dead_code)]
  docker: Docker,
  store: Store,
  executor: Executor,
  work_dir_base: PathBuf,
  named_caches: NamedCaches,
  immutable_inputs: ImmutableInputs,
  keep_sandboxes: KeepSandboxes,
}

impl CommandRunner {
  pub fn new(
    store: Store,
    executor: Executor,
    work_dir_base: PathBuf,
    named_caches: NamedCaches,
    immutable_inputs: ImmutableInputs,
    keep_sandboxes: KeepSandboxes,
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

        // Update env, replacing `{chroot}` placeholders with `/input`. This is the mount point
        // for the input root within the Docker container.
        //
        // DOCKER-TODO: When dealing with invocations from cached containers, `{chroot}` should be
        // replaced by the Pants executor process running inside the container.
        apply_chroot("/input", &mut req);

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
            (),
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
  type WorkdirToken = ();

  async fn run_in_workdir<'a, 'b, 'c>(
    &'a self,
    workdir_path: &'b Path,
    _workdir_token: (),
    req: Process,
    _exclusive_spawn: bool,
  ) -> Result<BoxStream<'c, Result<ChildOutput, String>>, String> {
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

    let config = bollard::container::Config {
      env: Some(env),
      cmd: Some(req.argv),
      working_dir: Some(working_dir),
      host_config: Some(bollard_stubs::models::HostConfig {
        binds: Some(vec![format!("{}:/pants-work", workdir_path_as_string)]),
        auto_remove: Some(self.keep_sandboxes == KeepSandboxes::Never),
        ..bollard_stubs::models::HostConfig::default()
      }),
      // DOCKER-TODO: Make `image` be a configuration option.
      image: Some("debian:latest".to_string()),
      attach_stdout: Some(true),
      attach_stderr: Some(true),
      ..bollard::container::Config::default()
    };

    let container = self
      .docker
      .create_container::<&str, String>(None, config)
      .await
      .map_err(|err| format!("Failed to create Docker container: {:?}", err))?;

    // DOCKER-TODO: Consider adding a drop guard to remove the container on error? (Although
    // auto-remove has been disabled if self.keep_sandboxes is "always" or "on failure.")

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

    let output_stream: BoxStream<'static, Result<ChildOutput, String>> = attach_result
      .output
      .filter_map(|log_msg| {
        futures::future::ready(match log_msg {
          Ok(LogOutput::StdOut { message }) => Some(Ok(ChildOutput::Stdout(message))),
          Ok(LogOutput::StdErr { message }) => Some(Ok(ChildOutput::Stderr(message))),
          _ => None,
        })
      })
      .boxed();

    let wait_options = bollard::container::WaitContainerOptions {
      condition: "next-exit",
    };
    let wait_stream = self
      .docker
      .wait_container(&container.id, Some(wait_options))
      .filter_map(|wr| {
        futures::future::ready(match wr {
          Ok(r) => {
            // DOCKER-TODO: How does Docker distinguish signal versus exit code? Improve
            // `ChildResults` to better support exit code vs signal vs error message?
            let status_code = r.status_code;
            Some(Ok(ChildOutput::Exit(ExitCode(status_code as i32))))
          }
          Err(err) => {
            // DOCKER-TODO: Consider a way to pass error messages back to child status collector.
            log::error!("Docker wait failure: {:?}", err);
            None
          }
        })
      })
      .boxed();

    let result_stream = futures::stream::select_all(vec![output_stream, wait_stream]);

    Ok(
      result_stream
        .map_err(|err| format!("Failed to consume Docker attach outputs: {:?}", err))
        .boxed(),
    )
  }
}
