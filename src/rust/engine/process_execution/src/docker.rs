// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::BTreeMap;
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bollard::container::{CreateContainerOptions, LogOutput, RemoveContainerOptions};
use bollard::exec::StartExecResults;
use bollard::image::CreateImageOptions;
use bollard::service::CreateImageInfo;
use bollard::{errors::Error as DockerError, Docker};
use futures::stream::BoxStream;
use futures::{StreamExt, TryFutureExt};
use log::Level;
use nails::execution::ExitCode;
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use store::{ImmutableInputs, Store};
use task_executor::Executor;
use workunit_store::{in_workunit, Metric, RunningWorkunit};

use crate::local::{
  apply_chroot, create_sandbox, prepare_workdir, setup_run_sh_script, CapturedWorkdir, ChildOutput,
  KeepSandboxes,
};
use crate::{
  Context, FallibleProcessResultWithPlatform, NamedCaches, Platform, Process, ProcessError,
  ProcessExecutionStrategy,
};

pub(crate) const SANDBOX_BASE_PATH_IN_CONTAINER: &str = "/pants-sandbox";
pub(crate) const NAMED_CACHES_BASE_PATH_IN_CONTAINER: &str = "/pants-named-caches";
pub(crate) const IMMUTABLE_INPUTS_BASE_PATH_IN_CONTAINER: &str = "/pants-immutable-inputs";

/// Process-wide image pull cache.
pub static IMAGE_PULL_CACHE: Lazy<ImagePullCache> = Lazy::new(ImagePullCache::new);

/// Process-wide Docker connection.
pub static DOCKER: Lazy<DockerOnceCell> = Lazy::new(DockerOnceCell::new);

/// `CommandRunner` that executes processes using a local Docker client.
pub struct CommandRunner<'a> {
  store: Store,
  executor: Executor,
  docker: &'a DockerOnceCell,
  work_dir_base: PathBuf,
  named_caches: NamedCaches,
  immutable_inputs: ImmutableInputs,
  keep_sandboxes: KeepSandboxes,
  container_cache: ContainerCache<'a>,
}

#[derive(Clone)]
pub struct DockerOnceCell {
  cell: Arc<OnceCell<Docker>>,
}

impl DockerOnceCell {
  pub fn new() -> Self {
    Self {
      cell: Arc::new(OnceCell::new()),
    }
  }

  pub fn initialized(&self) -> bool {
    self.cell.initialized()
  }

  pub async fn get(&self) -> Result<&Docker, String> {
    self
      .cell
      .get_or_try_init(async move {
        let docker = Docker::connect_with_local_defaults()
          .map_err(|err| format!("Failed to connect to local Docker: {err}"))?;

        let version = docker.version().await
          .map_err(|err| format!("Failed to obtain version from local Docker: {err}"))?;

        let api_version = version.api_version.as_ref().ok_or("Docker failed to report its API version.")?;
        let api_version_parts = api_version
          .split('.')
          .collect::<Vec<_>>();
        match api_version_parts[..] {
          [major, minor, ..] => {
            let major = (*major).parse::<usize>().map_err(|err| format!("Failed to decode Docker API major version `{major}`: {err}"))?;
            let minor = (*minor).parse::<usize>().map_err(|err| format!("Failed to decode Docker API minor version `{minor}`: {err}"))?;
            if major < 1 || (major == 1 && minor < 41) {
              return Err(format!("Pants requires Docker to support API version 1.41 or higher. Local Docker only supports: {:?}", &version.api_version));
            }
          }
          _ => return Err(format!("Unparseable API version `{}` returned by Docker.", &api_version)),
        }

        Ok(docker)
      })
      .await
  }
}

/// Represents a "scope" during which images will not be pulled again. This is usually associated
/// with a single `build_id` for a Pants session.
#[derive(Clone, Eq, PartialEq, Hash, PartialOrd, Ord)]
pub struct ImagePullScope(Arc<String>);

impl ImagePullScope {
  pub fn new(build_id: &str) -> Self {
    Self(Arc::new(build_id.to_string()))
  }
}

#[derive(Default)]
struct ImagePullCacheInner {
  /// Map an "image pull scope" (usually a build ID) to another map which is used to debounce
  /// image pull attempts made during that scope. The inner map goes from image name to a
  /// `OnceCell` which ensures that only one pull for that image occurs at a time within the
  /// relevant image pull scope.
  cache: BTreeMap<ImagePullScope, BTreeMap<String, Arc<OnceCell<()>>>>,
}

#[derive(Clone)]
pub struct ImagePullCache {
  /// Image pull cache and current build generation ID.
  inner: Arc<Mutex<ImagePullCacheInner>>,
}

fn docker_platform_identifier(platform: &Platform) -> &'static str {
  match platform {
    Platform::Linux_x86_64 => "linux/amd64",
    Platform::Linux_arm64 => "linux/arm64",
    Platform::Macos_x86_64 => "darwin/amd64",
    Platform::Macos_arm64 => "darwin/arm64",
  }
}

impl ImagePullCache {
  pub fn new() -> Self {
    Self {
      inner: Arc::default(),
    }
  }

  pub async fn pull_image(
    &self,
    docker: &Docker,
    image: &str,
    platform: &Platform,
    image_pull_scope: ImagePullScope,
    image_pull_policy: ImagePullPolicy,
  ) -> Result<(), String> {
    let image_cell = {
      let mut inner = self.inner.lock();

      let scope = inner
        .cache
        .entry(image_pull_scope)
        .or_insert_with(BTreeMap::default);

      let cell = scope
        .entry(image.to_string())
        .or_insert_with(|| Arc::new(OnceCell::new()));

      cell.clone()
    };

    image_cell
      .get_or_try_init(pull_image(docker, image, platform, image_pull_policy))
      .await?;

    Ok(())
  }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ImagePullPolicy {
  Always,
  IfMissing,
  Never,
  OnlyIfLatestOrMissing,
}

/// Pull an image given its name and the image pull policy. This method is debounced by
/// the "image pull cache" in the `CommandRunner`.
async fn pull_image(
  docker: &Docker,
  image: &str,
  platform: &Platform,
  policy: ImagePullPolicy,
) -> Result<(), String> {
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

  let (do_pull, pull_reason) = match (policy, image_exists) {
    (ImagePullPolicy::Always, _) => {
      (true, "the image pull policy is set to \"always\"")
    },
    (ImagePullPolicy::IfMissing, false) => {
      (true, "the image is missing locally")
    },
    (ImagePullPolicy::OnlyIfLatestOrMissing, false) => {
      (true, "the image is missing locally")
    },
    (ImagePullPolicy::OnlyIfLatestOrMissing, true) if has_latest_tag => {
      (true, "the image is present but the image tag is 'latest' and the image pull policy is set to pull images in this case")
    },
    (ImagePullPolicy::Never, false) => {
      return Err(format!(
        "Image `{}` was not found locally and Pants is configured to not attempt to pull",
        image
      ));
    }
    _ => (false, "")
  };

  if do_pull {
    in_workunit!(
      "pull_docker_image",
      Level::Info,
      desc = Some(format!(
        "Pulling Docker image `{image}` because {pull_reason}."
      )),
      |_workunit| async move {
        let create_image_options = CreateImageOptions::<String> {
          from_image: image.to_string(),
          platform: docker_platform_identifier(platform).to_string(),
          ..CreateImageOptions::default()
        };

        let mut result_stream = docker.create_image(Some(create_image_options), None, None);
        while let Some(msg) = result_stream.next().await {
          log::trace!("pull {}: {:?}", image, msg);
          match msg {
            Ok(msg) => match msg {
              CreateImageInfo {
                error: Some(error), ..
              } => {
                let error_msg = format!("Failed to pull Docker image `{image}`: {error}");
                log::error!("{error_msg}");
                return Err(error_msg);
              }
              CreateImageInfo {
                status: Some(status),
                ..
              } => {
                log::debug!("Docker pull status: {status}");
              }
              // Ignore content in other event fields, namely `id`, `progress`, and `progress_detail`.
              _ => (),
            },
            Err(err) => {
              return Err(format!(
                "Failed to pull Docker image `{}`: {:?}",
                image, err
              ))
            }
          }
        }

        Ok(())
      }
    )
    .await?;
  }

  Ok(())
}

impl<'a> CommandRunner<'a> {
  pub fn new(
    store: Store,
    executor: Executor,
    docker: &'a DockerOnceCell,
    image_pull_cache: &'a ImagePullCache,
    work_dir_base: PathBuf,
    named_caches: NamedCaches,
    immutable_inputs: ImmutableInputs,
    keep_sandboxes: KeepSandboxes,
  ) -> Result<Self, String> {
    let container_cache = ContainerCache::new(
      docker,
      image_pull_cache,
      &work_dir_base,
      &named_caches,
      &immutable_inputs,
    )?;

    Ok(CommandRunner {
      store,
      executor,
      docker,
      work_dir_base,
      named_caches,
      immutable_inputs,
      keep_sandboxes,
      container_cache,
    })
  }
}

impl fmt::Debug for CommandRunner<'_> {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    f.debug_struct("docker::CommandRunner")
      .finish_non_exhaustive()
  }
}

#[async_trait]
impl<'a> super::CommandRunner for CommandRunner<'a> {
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
      |workunit| async move {
        let mut workdir = create_sandbox(
          self.executor.clone(),
          &self.work_dir_base,
          &req.description,
          self.keep_sandboxes,
        )?;

        // Start working on a mutable version of the process.
        let mut req = req;

        // Update env, replacing `{chroot}` placeholders with the path to the sandbox
        // within the Docker container.
        let sandbox_relpath = workdir
          .path()
          .strip_prefix(&self.work_dir_base)
          .map_err(|err| {
            format!("Internal error - base directory was not prefix of sandbox directory: {err}")
          })?;
        let sandbox_path_in_container = Path::new(&SANDBOX_BASE_PATH_IN_CONTAINER)
          .join(sandbox_relpath)
          .into_os_string()
          .into_string()
          .map_err(|s| {
            format!(
              "Unable to convert sandbox path to string due to non UTF-8 characters: {:?}",
              s
            )
          })?;
        apply_chroot(&sandbox_path_in_container, &mut req);
        log::trace!(
          "sandbox_path_in_container = {:?}",
          &sandbox_path_in_container
        );

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
          Some(Path::new(NAMED_CACHES_BASE_PATH_IN_CONTAINER)),
          Some(Path::new(IMMUTABLE_INPUTS_BASE_PATH_IN_CONTAINER)),
        )
        .await?;

        workunit.increment_counter(Metric::DockerExecutionRequests, 1);

        let res = self
          .run_and_capture_workdir(
            req.clone(),
            context,
            self.store.clone(),
            self.executor.clone(),
            workdir.path().to_owned(),
            sandbox_path_in_container,
            exclusive_spawn,
            req.platform,
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

        match &res {
          Ok(_) => workunit.increment_counter(Metric::DockerExecutionSuccesses, 1),
          Err(_) => workunit.increment_counter(Metric::DockerExecutionErrors, 1),
        }

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
    self.container_cache.shutdown().await
  }
}

#[async_trait]
impl<'a> CapturedWorkdir for CommandRunner<'a> {
  type WorkdirToken = String;

  async fn run_in_workdir<'s, 'c, 'w, 'r>(
    &'s self,
    context: &'c Context,
    _workdir_path: &'w Path,
    sandbox_path_in_container: Self::WorkdirToken,
    req: Process,
    _exclusive_spawn: bool,
  ) -> Result<BoxStream<'r, Result<ChildOutput, String>>, String> {
    let docker = self.docker.get().await?;

    let env = req
      .env
      .iter()
      .map(|(key, value)| format!("{}={}", key, value))
      .collect::<Vec<_>>();

    let working_dir = req
      .working_directory
      .map(|relpath| Path::new(&sandbox_path_in_container).join(relpath))
      .unwrap_or_else(|| Path::new(&sandbox_path_in_container).to_path_buf())
      .into_os_string()
      .into_string()
      .map_err(|s| {
        format!(
          "Unable to convert working directory due to non UTF-8 characters: {:?}",
          s
        )
      })?;

    let image = match req.execution_strategy {
      ProcessExecutionStrategy::Docker(image) => Ok(image),
      _ => Err("The Docker execution strategy was not set on the Process, but the Docker CommandRunner was used.")
    }?;

    // Obtain ID of the base container in which to run the execution for this process.
    let container_id = self
      .container_cache
      .container_id_for_image(&image, &req.platform, &context.build_id)
      .await?;

    let config = bollard::exec::CreateExecOptions {
      env: Some(env),
      cmd: Some(req.argv),
      working_dir: Some(working_dir),
      attach_stdout: Some(true),
      attach_stderr: Some(true),
      ..bollard::exec::CreateExecOptions::default()
    };

    log::trace!("creating execution with config: {:?}", &config);

    let exec = docker
      .create_exec::<String>(&container_id, config)
      .await
      .map_err(|err| format!("Failed to create Docker execution in container: {:?}", err))?;

    log::trace!("created execution {}", &exec.id);

    let exec_result = docker
      .start_exec(&exec.id, None)
      .await
      .map_err(|err| format!("Failed to start Docker execution `{}`: {:?}", &exec.id, err))?;
    let mut output_stream = if let StartExecResults::Attached { output, .. } = exec_result {
      output.boxed()
    } else {
      panic!(
        "Unexpected value returned from start_exec: {:?}",
        exec_result
      );
    };

    log::trace!("started execution {}", &exec.id);

    let exec_id = exec.id.to_owned();
    let docker = docker.to_owned();

    let stream = async_stream::try_stream! {
      // Read output from the execution.
      while let Some(output_msg) = output_stream.next().await {
        match output_msg {
            Ok(LogOutput::StdOut { message }) => {
                log::trace!("execution {} wrote {} bytes to stdout", &exec_id, message.len());
                yield ChildOutput::Stdout(message);
            }
            Ok(LogOutput::StdErr { message }) => {
                log::trace!("execution {} wrote {} bytes to stderr", &exec_id, message.len());
                yield ChildOutput::Stderr(message);
            }
            Ok(_) => (),
            Err(err) => {
                log::trace!("error while capturing output of execution {}: {:?}", &exec_id, err);
            }
        }
      }

      let exec_metadata = docker
        .inspect_exec(&exec_id)
        .await
        .map_err(|err| format!("Failed to inspect Docker execution `{}`: {:?}", &exec_id, err))?;

      let status_code = exec_metadata
        .exit_code
        .ok_or_else(|| format!("Inspected execution `{}` for exit status but status was missing.", &exec_id))?;

      log::trace!("execution {} exited with status code {}", &exec_id, status_code);

      yield ChildOutput::Exit(ExitCode(status_code as i32));
    };

    Ok(stream.boxed())
  }
}

/// Caches running containers so that build actions can be invoked by running "executions"
/// within those cached containers.
struct ContainerCache<'a> {
  docker: &'a DockerOnceCell,
  image_pull_cache: &'a ImagePullCache,
  work_dir_base: String,
  named_caches_base_dir: String,
  immutable_inputs_base_dir: String,
  /// Cache that maps image name to container ID. async_oncecell::OnceCell is used so that
  /// multiple tasks trying to access an initializing container do not try to start multiple
  /// containers.
  #[allow(clippy::type_complexity)]
  containers: Mutex<BTreeMap<(String, Platform), Arc<OnceCell<String>>>>,
}

impl<'a> ContainerCache<'a> {
  pub fn new(
    docker: &'a DockerOnceCell,
    image_pull_cache: &'a ImagePullCache,
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
      image_pull_cache,
      work_dir_base,
      named_caches_base_dir,
      immutable_inputs_base_dir,
      containers: Mutex::default(),
    })
  }

  async fn make_container(
    docker: Docker,
    image: String,
    platform: Platform,
    image_pull_scope: ImagePullScope,
    image_pull_cache: ImagePullCache,
    work_dir_base: String,
    named_caches_base_dir: String,
    immutable_inputs_base_dir: String,
  ) -> Result<String, String> {
    // Pull the image.
    image_pull_cache
      .pull_image(
        &docker,
        &image,
        &platform,
        image_pull_scope,
        ImagePullPolicy::OnlyIfLatestOrMissing,
      )
      .await?;

    let config = bollard::container::Config {
      entrypoint: Some(vec!["/bin/sh".to_string()]),
      host_config: Some(bollard::service::HostConfig {
        binds: Some(vec![
          format!("{}:{}", work_dir_base, SANDBOX_BASE_PATH_IN_CONTAINER),
          format!(
            "{}:{}",
            named_caches_base_dir, NAMED_CACHES_BASE_PATH_IN_CONTAINER,
          ),
          // DOCKER-TODO: Consider making this bind mount read-only.
          format!(
            "{}:{}",
            immutable_inputs_base_dir, IMMUTABLE_INPUTS_BASE_PATH_IN_CONTAINER
          ),
        ]),
        // The init process ensures that child processes are properly reaped.
        init: Some(true),
        ..bollard::service::HostConfig::default()
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

    let create_options = CreateContainerOptions::<&str> {
      name: "",
      platform: Some(docker_platform_identifier(&platform)),
    };
    let container = docker
      .create_container::<&str, String>(Some(create_options), config)
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
  pub async fn container_id_for_image(
    &self,
    image: &str,
    platform: &Platform,
    build_generation: &str,
  ) -> Result<String, String> {
    let docker = self.docker.get().await?;
    let docker = docker.clone();

    let container_id_cell = {
      let mut containers = self.containers.lock();
      let cell = containers
        .entry((image.to_string(), *platform))
        .or_insert_with(|| Arc::new(OnceCell::new()));
      cell.clone()
    };

    let work_dir_base = self.work_dir_base.clone();
    let named_caches_base_dir = self.named_caches_base_dir.clone();
    let immutable_inputs_base_dir = self.immutable_inputs_base_dir.clone();
    let image_pull_scope = ImagePullScope::new(build_generation);

    let container_id = container_id_cell
      .get_or_try_init(async move {
        Self::make_container(
          docker,
          image.to_string(),
          *platform,
          image_pull_scope,
          self.image_pull_cache.clone(),
          work_dir_base,
          named_caches_base_dir,
          immutable_inputs_base_dir,
        )
        .await
      })
      .await?;

    Ok(container_id.to_owned())
  }

  pub async fn shutdown(&self) -> Result<(), String> {
    // Skip shutting down if Docker was never used in the first place.
    if self.containers.lock().is_empty() {
      return Ok(());
    }

    let docker = match self.docker.get().await {
      Ok(d) => d,
      Err(err) => {
        return Err(format!(
          "Failed to get Docker connection during container removal: {err}"
        ))
      }
    };

    #[allow(clippy::needless_collect)]
    // allow is necessary otherwise will get "temporary value dropped while borrowed" error
    let container_ids = self
      .containers
      .lock()
      .values()
      .flat_map(|v| v.get())
      .cloned()
      .collect::<Vec<_>>();

    let removal_futures = container_ids.into_iter().map(|id| async move {
      let remove_options = RemoveContainerOptions {
        force: true,
        ..RemoveContainerOptions::default()
      };
      docker
        .remove_container(&id, Some(remove_options))
        .await
        .map_err(|err| format!("Failed to remove Docker container `{id}`: {err:?}"))
    });

    futures::future::try_join_all(removal_futures).await?;
    Ok(())
  }
}
