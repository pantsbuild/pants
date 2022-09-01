use std::collections::BTreeMap;
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bollard::container::LogOutput;
use bollard::image::CreateImageOptions;
use bollard::{errors::Error as DockerError, Docker};
use futures::stream::BoxStream;
use futures::{StreamExt, TryFutureExt};
use nails::execution::ExitCode;
use parking_lot::Mutex;
use store::Store;
use task_executor::Executor;
use workunit_store::{in_workunit, RunningWorkunit};

use crate::local::{
  apply_chroot, create_sandbox, prepare_workdir, setup_run_sh_script, CapturedWorkdir, ChildOutput,
  KeepSandboxes,
};
use crate::{
  Context, FallibleProcessResultWithPlatform, ImmutableInputs, NamedCaches, Platform, Process,
  ProcessError,
};

pub(crate) const SANDBOX_PATH_IN_CONTAINER: &str = "/pants-sandbox";
pub(crate) const NAMED_CACHES_PATH_IN_CONTAINER: &str = "/pants-named-caches";
pub(crate) const IMMUTABLE_INPUTS_PATH_IN_CONTAINER: &str = "/pants-immutable-inputs";

/// `CommandRunner` that executes processes using a local Docker client.
pub struct CommandRunner {
  docker: OnceCell<Docker>,
  store: Store,
  executor: Executor,
  work_dir_base: PathBuf,
  named_caches: NamedCaches,
  immutable_inputs: ImmutableInputs,
  keep_sandboxes: KeepSandboxes,
  image_pull_cache: Mutex<ImageCache>,
  image_pull_policy: ImagePullPolicy,
}

#[derive(Default)]
struct ImageCache {
  /// Maps an image name to a `OnceCell` used to debounce image pull attempts made during this
  /// particular run.
  cache: BTreeMap<String, Arc<OnceCell<()>>>,

  /// Stores the current "build generation" during which this command runner will not attempt
  /// to pull an image again. This is populated from `build_id` field on `Context`. `cache`
  /// will be cleared when the generation changes.
  generation: String,
}

#[allow(dead_code)] // TODO: temporary until docker command runner is hooked up
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ImagePullPolicy {
  Always,
  IfMissing,
  Never,
  OnlyIfLatestOrMissing,
}

/// Pull an image given its name and the image pull policy. This method is debounced by
/// the "image pull cache" in the `CommandRunner`.
async fn pull_image(docker: &Docker, image: &str, policy: ImagePullPolicy) -> Result<(), String> {
  let has_latest_tag = {
    if let Some((_, suffix)) = image.rsplit_once(':') {
      suffix == "latest"
    } else {
      false
    }
  };

  let image_exists = {
    match docker.inspect_image(image).await {
      Ok(_) => true,
      Err(DockerError::DockerResponseServerError {
        status_code: 404, ..
      }) => false,
      Err(err) => {
        return Err(format!(
          "Failed to inspect Docker image `{}`: {:?}",
          image, err
        ))
      }
    }
  };

  let do_pull = match (policy, image_exists) {
    (ImagePullPolicy::Always, _) => true,
    (ImagePullPolicy::IfMissing, false) => true,
    (ImagePullPolicy::OnlyIfLatestOrMissing, false) => true,
    (ImagePullPolicy::OnlyIfLatestOrMissing, true) if has_latest_tag => true,
    (ImagePullPolicy::Never, false) => {
      return Err(format!(
        "Image `{}` was not found locally and Pants is configured to not attempt to pull",
        image
      ));
    }
    _ => false,
  };

  if do_pull {
    let create_image_options = CreateImageOptions::<String> {
      from_image: image.to_string(),
      ..CreateImageOptions::default()
    };

    let mut result_stream = docker.create_image(Some(create_image_options), None, None);
    while let Some(msg) = result_stream.next().await {
      log::trace!("pull {}: {:?}", image, msg);
      if let Err(err) = msg {
        return Err(format!(
          "Failed to pull Docker image `{}`: {:?}",
          image, err
        ));
      }
    }
  }

  Ok(())
}

impl CommandRunner {
  pub fn new(
    store: Store,
    executor: Executor,
    work_dir_base: PathBuf,
    named_caches: NamedCaches,
    immutable_inputs: ImmutableInputs,
    keep_sandboxes: KeepSandboxes,
    image_pull_policy: ImagePullPolicy,
  ) -> Result<Self, String> {
    Ok(CommandRunner {
      docker: OnceCell::new(),
      store,
      executor,
      work_dir_base,
      named_caches,
      immutable_inputs,
      keep_sandboxes,
      image_pull_cache: Mutex::default(),
      image_pull_policy,
    })
  }

  async fn docker(&self) -> Result<&Docker, String> {
    self
      .docker
      .get_or_try_init(async move {
        let docker = Docker::connect_with_local_defaults()
          .map_err(|err| format!("Failed to connect to local Docker: {err}"))?;

        docker
          .ping()
          .await
          .map_err(|err| format!("Failed to receive response from local Docker: {err}"))?;

        Ok(docker)
      })
      .await
  }

  async fn pull_image(&self, image: &str, build_generation: &str) -> Result<(), String> {
    let image_cell = {
      let mut image_pull_cache = self.image_pull_cache.lock();

      if build_generation != image_pull_cache.generation {
        image_pull_cache.cache.clear();
        image_pull_cache.generation = build_generation.to_string();
      }

      let cell = image_pull_cache
        .cache
        .entry(image.to_string())
        .or_insert_with(|| Arc::new(OnceCell::new()));
      cell.clone()
    };

    image_cell
      .get_or_try_init(pull_image(
        self.docker().await?,
        image,
        self.image_pull_policy,
      ))
      .await?;
    Ok(())
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

        // Update env, replacing `{chroot}` placeholders with `/pants-sandbox`. This is the mount point
        // for the sandbox directory within the Docker container.
        //
        // DOCKER-TODO: With cached containers, the destination in the container
        // will need to be unique within that container to avoid conflicts.
        apply_chroot(SANDBOX_PATH_IN_CONTAINER, &mut req);

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
          Some(Path::new(NAMED_CACHES_PATH_IN_CONTAINER)),
          Some(Path::new(IMMUTABLE_INPUTS_PATH_IN_CONTAINER)),
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

  async fn run_in_workdir<'s, 'c, 'w, 'r>(
    &'s self,
    context: &'c Context,
    workdir_path: &'w Path,
    (immutable_inputs_workdir, named_caches_workdir): Self::WorkdirToken,
    req: Process,
    _exclusive_spawn: bool,
  ) -> Result<BoxStream<'r, Result<ChildOutput, String>>, String> {
    let docker = self.docker().await?;

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
      .map(|relpath| Path::new(SANDBOX_PATH_IN_CONTAINER).join(&relpath))
      .unwrap_or_else(|| Path::new(SANDBOX_PATH_IN_CONTAINER).to_path_buf())
      .into_os_string()
      .into_string()
      .map_err(|s| {
        format!(
          "Unable to convert working directory due to non UTF-8 characters: {:?}",
          s
        )
      })?;

    let image = req
      .docker_image
      .ok_or("docker_image not set on the Process, but the Docker CommandRunner was used.")?;

    // Attempt to pull the image (if so configured by the image pull policy). The `build_id` is
    // used to determine when images should again be pulled (for example, when the "always"
    // image pull policy is set).
    self.pull_image(&image, &context.build_id).await?;

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
          format!("{}:{}", workdir_path_as_string, SANDBOX_PATH_IN_CONTAINER),
          // DOCKER-TODO: Consider making this bind mount read-only.
          format!(
            "{}:{}",
            immutable_inputs_workdir_as_string, IMMUTABLE_INPUTS_PATH_IN_CONTAINER
          ),
          format!(
            "{}:{}",
            named_caches_workdir_as_string, NAMED_CACHES_PATH_IN_CONTAINER
          ),
        ]),
        init: Some(true),
        ..bollard_stubs::models::HostConfig::default()
      }),
      image: Some(image),
      attach_stdout: Some(true),
      attach_stderr: Some(true),
      ..bollard::container::Config::default()
    };

    log::trace!("creating container with config: {:?}", &config);

    let container = docker
      .create_container::<&str, String>(None, config)
      .await
      .map_err(|err| format!("Failed to create Docker container: {:?}", err))?;

    log::trace!("created container {}", &container.id);

    docker
      .start_container::<String>(&container.id, None)
      .await
      .map_err(|err| {
        format!(
          "Failed to start Docker container `{}`: {:?}",
          &container.id, err
        )
      })?;

    log::trace!("started container {}", &container.id);

    let container_id = container.id.to_owned();
    let keep_sandboxes = self.keep_sandboxes;
    let docker = docker.clone();

    let stream = async_stream::try_stream! {
      // Wait for the container to exit.
      let status_code = loop {
        let wait_options = bollard::container::WaitContainerOptions {
          condition: "not-running",
        };
        let mut wait_stream = docker
          .wait_container(&container.id, Some(wait_options))
          .boxed();

        let wait_msg = match wait_stream.next().await {
          Some(msg) => msg,
          None => {
            log::trace!("Docker wait_container monitoring stream closed early. Reconnecting ...");
            continue
          },
        };

        let status_code = wait_msg
          .map_err(|err| format!("Docker wait_container failure for container {}: {:?}", &container_id, err))?
          .status_code;

        break status_code;
      };

      log::trace!("container {} exited with status code {}", &container_id, status_code);

      let attach_options = bollard::container::AttachContainerOptions::<String> {
        stdout: Some(true),
        stderr: Some(true),
        logs: Some(true),
        ..bollard::container::AttachContainerOptions::default()
      };

      let attach_result = docker
        .attach_container(&container.id, Some(attach_options))
        .await
        .map_err(|err| {
          format!(
            "Failed to attach to Docker container `{}`: {:?}",
            &container_id, err
          )
        })?;

      log::trace!("attached to container {}", &container.id);

      let mut output_stream = attach_result.output.boxed();

      while let Some(output_msg) = output_stream.next().await {
        match output_msg {
            Ok(LogOutput::StdOut { message }) => {
                log::trace!("container {} wrote {} bytes to stdout", &container_id, message.len());
                yield ChildOutput::Stdout(message);
            }
            Ok(LogOutput::StdErr { message }) => {
                log::trace!("container {} wrote {} bytes to stderr", &container_id, message.len());
                yield ChildOutput::Stderr(message);
            }
            Ok(_) => (),
            Err(err) => {
                log::trace!("error while capturing output of container {}: {:?}", &container_id, err);
            }
        }
      }

      yield ChildOutput::Exit(ExitCode(status_code as i32));

      let do_remove_container = match keep_sandboxes {
        KeepSandboxes::Always => false,
        KeepSandboxes::Never => true,
        KeepSandboxes::OnFailure => status_code == 0,
      };

      if do_remove_container {
        let remove_options = bollard::container::RemoveContainerOptions {
          force: true,
          ..bollard::container::RemoveContainerOptions::default()
        };

        let remove_result = docker
          .remove_container(&container_id, Some(remove_options))
          .await
          .map_err(|err| format!("Failed to remove container `{}`: {:?}", &container_id, err));
        if let Err(err) = remove_result {
          log::warn!("{}", err);
        }
      }
    };

    Ok(stream.boxed())
  }
}

/// Caches running containers so that build actions can be invoked by running executions
/// within those cached containers.
struct ContainerCache {
  docker: Docker,
  work_dir_base: String,
  named_caches_base_dir: String,
  immutable_inputs_base_dir: String,
  /// Cache that maps image name to container ID. async_oncecell::OnceCell is used so that
  /// multiple tasks trying to access an initializing container do not try to start multiple
  /// containers.
  containers: Mutex<BTreeMap<String, Arc<OnceCell<String>>>>,
}

impl ContainerCache {
  pub fn new(
    docker: Docker,
    work_dir_base: &Path,
    named_caches: &NamedCaches,
    immutable_inputs: &ImmutableInputs,
  ) -> Result<Self, String> {
    let work_dir_base = work_dir_base
      .to_path_buf()
      .into_os_string()
      .into_string()
      .map_err(|s| {
        format!(
          "Unable to convert workdir_path due to non UTF-8 characters: {:?}",
          s
        )
      })?;

    let named_caches_base_dir = named_caches
      .base_dir()
      .to_path_buf()
      .into_os_string()
      .into_string()
      .map_err(|s| {
        format!(
          "Unable to convert named_caches workdir due to non UTF-8 characters: {:?}",
          s
        )
      })?;

    let immutable_inputs_base_dir = immutable_inputs
      .workdir()
      .to_path_buf()
      .into_os_string()
      .into_string()
      .map_err(|s| {
        format!(
          "Unable to convert immutable_inputs base dir due to non UTF-8 characters: {:?}",
          s
        )
      })?;

    Ok(Self {
      docker,
      work_dir_base,
      named_caches_base_dir,
      immutable_inputs_base_dir,
      containers: Mutex::default(),
    })
  }

  async fn make_container(
    docker: Docker,
    image: String,
    work_dir_base: String,
    named_caches_base_dir: String,
    immutable_inputs_base_dir: String,
  ) -> Result<String, String> {
    let config = bollard::container::Config {
      entrypoint: Some(vec!["/bin/sh".to_string()]),
      host_config: Some(bollard_stubs::models::HostConfig {
        binds: Some(vec![
          format!("{}:{}", work_dir_base, SANDBOX_PATH_IN_CONTAINER),
          // DOCKER-TODO: Consider making this bind mount read-only.
          format!(
            "{}:{}",
            named_caches_base_dir, IMMUTABLE_INPUTS_PATH_IN_CONTAINER
          ),
          format!(
            "{}:{}",
            immutable_inputs_base_dir, NAMED_CACHES_PATH_IN_CONTAINER
          ),
        ]),
        // The init process ensures that child processes are properly reaped.
        init: Some(true),
        ..bollard_stubs::models::HostConfig::default()
      }),
      image: Some(image.clone()),
      tty: Some(true),
      open_stdin: Some(true),
      ..bollard::container::Config::default()
    };

    log::trace!(
      "creating cached container with config for image `{}`: {:?}",
      image,
      &config
    );

    let container = docker
      .create_container::<&str, String>(None, config)
      .await
      .map_err(|err| format!("Failed to create Docker container: {:?}", err))?;

    log::trace!(
      "created container `{}` for image `{}`",
      &container.id,
      image
    );

    docker
      .start_container::<String>(&container.id, None)
      .await
      .map_err(|err| {
        format!(
          "Failed to start Docker container `{}` for image `{}`: {:?}",
          &container.id, image, err
        )
      })?;

    log::trace!(
      "started container `{}` for image `{}`",
      &container.id,
      image
    );

    Ok(container.id)
  }

  /// Return the container ID of a container running `image` for use as a place to invoke
  /// build actions as executions within the cached container.
  pub async fn container_id_for_image(&self, image: &str) -> Result<&String, String> {
    let container_id_cell = {
      let mut containers = self.containers.lock();
      let cell = containers
        .entry(image.to_string())
        .or_insert_with(|| Arc::new(OnceCell::new()));
      cell.clone()
    };

    let docker = self.docker.clone();
    let work_dir_base = self.work_dir_base.clone();
    let named_caches_base_dir = self.named_caches_base_dir.clone();
    let immutable_inputs_base_dir = self.immutable_inputs_base_dir.clone();

    container_id_cell
      .get_or_try_init(async move {
        Self::make_container(
          docker,
          image.to_string(),
          work_dir_base,
          named_caches_base_dir,
          immutable_inputs_base_dir,
        )
        .await
      })
      .await
  }
}
