// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, HashMap};
use std::ffi::OsStr;
use std::fmt;
use std::io::Write;
use std::net::ToSocketAddrs;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::str;
use std::sync::Arc;
use std::time::Duration;

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bollard::auth::DockerCredentials;
use bollard::container::{
    CreateContainerOptions, ListContainersOptions, LogOutput, RemoveContainerOptions,
};
use bollard::exec::StartExecResults;
use bollard::image::CreateImageOptions;
use bollard::models::ContainerState;
use bollard::secret::{ContainerInspectResponse, ContainerStateStatusEnum};
use bollard::service::CreateImageInfo;
use bollard::volume::CreateVolumeOptions;
use bollard::{Docker, errors::Error as DockerError};
use bytes::{Bytes, BytesMut};
use futures::future::join_all;
use fs::RelativePath;
use futures::stream::BoxStream;
use futures::{FutureExt, StreamExt};
use hashing::Digest;
use itertools::Itertools;
use log::Level;
use maplit::hashmap;
use nails::execution::ExitCode;
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use shell_quote::Bash;
use store::{ImmutableInputs, Store};
use task_executor::Executor;
use workunit_store::{Metric, RunningWorkunit, in_workunit};

use process_execution::local::{
    CapturedWorkdir, CapturedWorkdirError, ChildOutput, KeepSandboxes, USER_EXECUTABLE_MODE,
    apply_chroot, collect_child_outputs, create_sandbox, prepare_workdir,
};
use process_execution::{
    Context, FallibleProcessResultWithPlatform, NamedCaches, Platform, Process, ProcessError,
    ProcessExecutionStrategy,
};

pub(crate) const SANDBOX_BASE_PATH_IN_CONTAINER: &str = "/pants-sandbox";
pub(crate) const NAMED_CACHES_BASE_PATH_IN_CONTAINER: &str = "/pants-named-caches";
pub(crate) const IMMUTABLE_INPUTS_BASE_PATH_IN_CONTAINER: &str = "/pants-immutable-inputs";
pub(crate) const PANTS_CONTAINER_ENVIRONMENT_LABEL_KEY: &str = "org.pantsbuild.environment";
pub(crate) const CONTAINER_CLEANUP_TIMEOUT_SECONDS: u64 = 60;

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
    immutable_inputs: ImmutableInputs,
    pub(crate) container_cache: ContainerCache<'a>,
}

/// Struct for a single-initialization Docker client.
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

    async fn remove_old_images(docker: &Docker) -> Result<(), Vec<String>> {
        let removal_tasks = docker
            .list_containers(Some(ListContainersOptions::<&str> {
                filters: hashmap!{"label" => vec![PANTS_CONTAINER_ENVIRONMENT_LABEL_KEY], "status" => vec!["exited", "dead"]},
                ..ListContainersOptions::default()
            }))
            .await
            .map_err(|err| {
                vec![format!(
                    "An error occurred when listing docker containers\n\n{err}"
                )]
            })?
            .into_iter()
            .map(|summary| {
                let docker = docker.clone();
                tokio::spawn(async move {
                    match summary.id {
                        Some(container_id) => {
                            log::debug!("Removing stale container {container_id} with {PANTS_CONTAINER_ENVIRONMENT_LABEL_KEY} label");
                            docker
                            .remove_container(
                                container_id.as_str(),
                                Some(RemoveContainerOptions {
                                    force: true,
                                    ..RemoveContainerOptions::default()
                                }),
                            )
                            .await
                            .map_err(|err| {
                                format!("Failed to remove container {container_id}:\n{err}")
                            })
                        },
                        None => Err(format!(
                            "No container id attached to summary:\n{summary:#?}"
                        )),
                    }
                })
            });
        let errors: Vec<String> = join_all(removal_tasks)
            .await
            .into_iter()
            .filter_map(|res| match res {
                Ok(Ok(_)) => None,
                Ok(Err(s)) => Some(s),
                Err(je) => Some(je.to_string()),
            })
            .collect();
        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors)
        }
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

        let cleanup_docker = docker.clone();
        tokio::spawn(async move {
            let message = match tokio::time::timeout(Duration::from_secs(CONTAINER_CLEANUP_TIMEOUT_SECONDS), Self::remove_old_images(&cleanup_docker)).await {
                Ok(Ok(_)) => return,
                Ok(Err(removal_errors)) => format!("The following errors occurred when attempting to remove old containers:\n\n{}", removal_errors.join("\n\n")),
                Err(_) => format!("Attempt to clean up old containers timed out after {CONTAINER_CLEANUP_TIMEOUT_SECONDS} seconds"),
            };
            log::warn!("{}", message)
        });
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
        executor: &Executor,
        image: &str,
        platform: &Platform,
        image_pull_scope: ImagePullScope,
        image_pull_policy: ImagePullPolicy,
    ) -> Result<(), String> {
        let image_cell = {
            let mut inner = self.inner.lock();

            let scope = inner.cache.entry(image_pull_scope).or_default();

            let cell = scope
                .entry(image.to_string())
                .or_insert_with(|| Arc::new(OnceCell::new()));

            cell.clone()
        };

        image_cell
            .get_or_try_init(pull_image(
                docker,
                executor,
                image,
                platform,
                image_pull_policy,
            ))
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

async fn credentials_for_image(
    executor: &Executor,
    image: &str,
) -> Result<Option<DockerCredentials>, String> {
    // An image name has an optional domain component before the first `/`. While the grammar (linked
    // below) seems to imply that the domain can be statically differentiated from the path, it's not
    // clear how. So to confirm that it is a domain, we attempt to DNS resolve it.
    //
    // https://github.com/distribution/distribution/blob/e5d5810851d1f17a5070e9b6f940d8af98ea3c29/reference/reference.go#L4-L26
    let Some((server, _)) = image.split_once('/') else {
        return Ok(None);
    };
    let server = server.to_owned();

    executor
        .spawn_blocking(
            move || {
                // Resolve the server as a DNS name to confirm that it is actually a registry.
                let Ok(_) = (server.as_ref(), 80)
                    .to_socket_addrs()
                    .or_else(|_| server.to_socket_addrs())
                else {
                    return Ok(None);
                };

                // TODO: https://github.com/keirlawson/docker_credential/issues/7 means that this will only
                // work for credential helpers and credentials encoded directly in the docker config,
                // rather than for general credStore implementations.
                let credential = match docker_credential::get_credential(&server) {
                    Ok(credential) => credential,
                    Err(e) => {
                        log::warn!(
                            "Failed to retrieve Docker credentials for server `{}`: {}",
                            server,
                            e
                        );
                        return Ok(None);
                    }
                };

                let bollard_credentials = match credential {
                    docker_credential::DockerCredential::IdentityToken(token) => {
                        DockerCredentials {
                            identitytoken: Some(token),
                            ..DockerCredentials::default()
                        }
                    }
                    docker_credential::DockerCredential::UsernamePassword(username, password) => {
                        DockerCredentials {
                            username: Some(username),
                            password: Some(password),
                            ..DockerCredentials::default()
                        }
                    }
                };

                Ok(Some(bollard_credentials))
            },
            |e| Err(format!("Credentials task failed: {e}")),
        )
        .await
}

/// Pull an image given its name and the image pull policy. This method is debounced by
/// the "image pull cache" in the `CommandRunner`.
async fn pull_image(
    docker: &Docker,
    executor: &Executor,
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
            Err(err) => return Err(format!("Failed to inspect Docker image `{image}`: {err:?}")),
        }
    };

    let (do_pull, pull_reason) = match (policy, image_exists) {
        (ImagePullPolicy::Always, _) => (true, "the image pull policy is set to \"always\""),
        (ImagePullPolicy::IfMissing, false) => (true, "the image is missing locally"),
        (ImagePullPolicy::OnlyIfLatestOrMissing, false) => (true, "the image is missing locally"),
        (ImagePullPolicy::OnlyIfLatestOrMissing, true) if has_latest_tag => (
            true,
            "the image is present but the image tag is 'latest' and the image pull policy is set to pull images in this case",
        ),
        (ImagePullPolicy::Never, false) => {
            return Err(format!(
                "Image `{image}` was not found locally and Pants is configured to not attempt to pull"
            ));
        }
        _ => (false, ""),
    };

    if do_pull {
        in_workunit!(
            "pull_docker_image",
            Level::Info,
            desc = Some(format!(
                "Pulling Docker image `{image}` because {pull_reason}."
            )),
            |_workunit| async move {
                let credentials = credentials_for_image(executor, image)
                    .await
                    .map_err(|e| format!("Failed to pull Docker image `{image}`: {e}"))?;

                let create_image_options = CreateImageOptions::<String> {
                    from_image: image.to_string(),
                    platform: docker_platform_identifier(platform).to_string(),
                    ..CreateImageOptions::default()
                };

                let mut result_stream =
                    docker.create_image(Some(create_image_options), None, credentials);
                while let Some(msg) = result_stream.next().await {
                    log::trace!("pull {}: {:?}", image, msg);
                    match msg {
                        Ok(msg) => match msg {
                            CreateImageInfo {
                                error: Some(error), ..
                            } => {
                                return Err(format!(
                                    "Failed to pull Docker image `{image}`: {error}"
                                ));
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
                            return Err(format!("Failed to pull Docker image `{image}`: {err:?}"));
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
        immutable_inputs: ImmutableInputs,
    ) -> Result<Self, String> {
        let container_cache = ContainerCache::new(
            docker,
            image_pull_cache,
            executor.clone(),
            &work_dir_base,
            &immutable_inputs,
        )?;

        Ok(CommandRunner {
            store,
            executor,
            docker,
            work_dir_base,
            immutable_inputs,
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

const MAX_RUN_ATTEMPTS: usize = 2;

#[async_trait]
impl process_execution::CommandRunner for CommandRunner<'_> {
    async fn run(
        &self,
        context: Context,
        _workunit: &mut RunningWorkunit,
        req: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
        let (image_name, image_platform) = {
            let ProcessExecutionStrategy::Docker(image) = &req.execution_environment.strategy
            else {
                return Err(ProcessError::Unclassified(
                    "The Docker execution strategy was not set on the Process, but \
                    the Docker CommandRunner was used."
                        .to_owned(),
                ));
            };
            (image, &req.execution_environment.platform)
        };
        let keep_sandboxes = req.execution_environment.local_keep_sandboxes;
        let mut errors: Vec<String> = vec![];
        while errors.len() < MAX_RUN_ATTEMPTS {
            // Make a mutable copy of the process in the closure
            let mut mreq = req.clone();
            let context = context.clone();
            let process_result: Result<FallibleProcessResultWithPlatform, CapturedWorkdirError> = in_workunit!(
                "run_local_process_via_docker",
                req.level,
                // NB: See engine::nodes::NodeKey::workunit_level for more information on why this workunit
                // renders at the Process's level.
                desc = Some(req.description.clone()),
                |workunit| async move {
                    let mut workdir = create_sandbox(
                        self.executor.clone(),
                        &self.work_dir_base,
                        &mreq.description,
                        keep_sandboxes,
                    )?;
                    // Obtain ID of the base container in which to run the execution for this process.
                    let (container_id, named_caches) = self.container_cache.container_for_image(
                        image_name,
                        image_platform,
                        &context.build_id,
                        mreq.execution_environment.name.as_ref().unwrap(),
                    )
                    .await?;
                    // Compute the absolute working directory within the container, and update the env to
                    // replace `{chroot}` placeholders with the path to the sandbox within the Docker container.
                    let working_dir = {
                        let sandbox_relpath = workdir.path()
                            .strip_prefix(&self.work_dir_base)
                            .map_err(|err| format!("Internal error - base directory was not prefix of sandbox directory: {err}"))?;
                        let sandbox_path_in_container = Path::new(&SANDBOX_BASE_PATH_IN_CONTAINER)
                            .join(sandbox_relpath)
                            .into_os_string()
                            .into_string()
                            .map_err(|s| format!("Unable to convert sandbox path to string due to non UTF-8 characters: {s:?}"))?;
                        apply_chroot(&sandbox_path_in_container, &mut mreq);
                        log::trace!("sandbox_path_in_container = {:?}", &sandbox_path_in_container);
                        mreq.working_directory
                            .as_ref()
                            .map(|relpath| Path::new(&sandbox_path_in_container).join(relpath))
                            .unwrap_or_else(|| Path::new(&sandbox_path_in_container).to_path_buf())
                            .into_os_string()
                            .into_string()
                            .map_err(|s| format!("Unable to convert working directory due to non UTF-8 characters: {s:?}"))?
                    };
                    // Prepare the workdir.
                    // DOCKER-NOTE: The input root will be bind mounted into the container.
                    let exclusive_spawn = prepare_workdir(
                        workdir.path().to_owned(),
                        &self.work_dir_base,
                        &mreq,
                        mreq.input_digests.inputs.clone(),
                        &self.store,
                        // Sandboxer is not needed for docker execution, since the executing
                        // process is not a subprocess of ours, but a process in a docker container.
                        None,
                        &named_caches,
                        &self.immutable_inputs,
                        Some(Path::new(NAMED_CACHES_BASE_PATH_IN_CONTAINER)),
                        Some(Path::new(IMMUTABLE_INPUTS_BASE_PATH_IN_CONTAINER)),
                    ).await?;

                    workunit.increment_counter(Metric::DockerExecutionRequests, 1);
                    let res = self.run_and_capture_workdir(
                        mreq.clone(),
                        context,
                        self.store.clone(),
                        self.executor.clone(),
                        workdir.path().to_owned(),
                        (container_id, working_dir),
                        exclusive_spawn,
                    ).await;
                    match &res {
                        Ok(_) => workunit.increment_counter(Metric::DockerExecutionSuccesses, 1),
                        Err(_) => workunit.increment_counter(Metric::DockerExecutionErrors, 1),
                    };
                    if keep_sandboxes == KeepSandboxes::Always || (
                        keep_sandboxes == KeepSandboxes::OnFailure &&
                            res.as_ref().map(|r| r.exit_code).unwrap_or(1) != 0
                    ) {
                        workdir.keep(&mreq.description);
                        setup_docker_run_sh_script(
                            workdir.path(),
                            &mreq.env,
                            &mreq.working_directory,
                            &mreq.argv,
                            workdir.path(),
                            image_name,
                            &self.work_dir_base,
                            self.immutable_inputs.workdir(),
                        )?;
                    }
                    res
                }
            ).await;
            match process_result {
                Err(CapturedWorkdirError::Retryable(message)) => {
                    errors.push(message);
                    self.container_cache
                        .prune_container(image_name, image_platform)
                        .await;
                }
                _ => {
                    return process_result
                        .map_err(|cwe| ProcessError::Unclassified(cwe.to_string()));
                }
            };
        }
        Err(ProcessError::Unclassified(format!(
            "Failed to execute due to missing container: {:#?}\n\n{}",
            req,
            errors
                .iter()
                .enumerate()
                .map(|(i, s)| format!("Attempt #{} failed due to: {}", i + 1, s))
                .join("\n")
        )))
    }

    async fn shutdown(&self) -> Result<(), String> {
        self.container_cache.shutdown().await
    }
}

#[async_trait]
impl CapturedWorkdir for CommandRunner<'_> {
    type WorkdirToken = (String, String);

    // TODO: This method currently violates the `Drop` constraint of `CapturedWorkdir`, because the
    // Docker container is not necessarily killed when the returned value is Dropped.
    //
    // see https://github.com/pantsbuild/pants/issues/18210
    async fn run_in_workdir<'s, 'c, 'w, 'r>(
        &'s self,
        _context: &'c Context,
        _workdir_path: &'w Path,
        (container_id, working_dir): Self::WorkdirToken,
        req: Process,
        _exclusive_spawn: bool,
    ) -> Result<BoxStream<'r, Result<ChildOutput, String>>, CapturedWorkdirError> {
        let docker = self.docker.get().await?;

        Command::new(req.argv)
            .env(req.env)
            .working_dir(working_dir)
            .spawn(docker, container_id)
            .await
            .map_err(|spawn_err: CommandSpawnError| -> CapturedWorkdirError {
                match spawn_err.err {
                    // Rather than trying to handle every possible error code, we just restart the container and retry any DockerResponseServerErrors
                    DockerError::DockerResponseServerError { .. } => {
                        CapturedWorkdirError::Retryable(spawn_err.message)
                    }
                    _ => CapturedWorkdirError::Fatal(spawn_err.message),
                }
            })
    }

    async fn prepare_workdir_for_capture(
        &self,
        _context: &Context,
        _workdir_path: &Path,
        (container_id, working_dir): Self::WorkdirToken,
        req: &Process,
    ) -> Result<(), CapturedWorkdirError> {
        // Docker on Linux will frequently produce root-owned output files in bind mounts, because we
        // do not assume anything about the users that exist in the image. But Docker on macOS (at least
        // version 14.6.2 using gRPC-FUSE filesystem virtualization) creates files in bind mounts as the
        // user running Docker. See https://github.com/pantsbuild/pants/issues/18306.
        //
        // TODO: Changing permissions allows the files to be captured, but not for them to be removed.
        // See https://github.com/pantsbuild/pants/issues/18329.
        if matches!(
            Platform::current()?,
            Platform::Macos_x86_64 | Platform::Macos_arm64
        ) {
            return Ok(());
        }

        let docker = self.docker.get().await?;

        let args = ["chmod", "a+r", "-R"]
            .into_iter()
            .map(OsStr::new)
            .chain(
                req.output_files
                    .iter()
                    .chain(req.output_directories.iter())
                    .map(|p| p.as_ref().as_os_str()),
            )
            .map(|s| {
                s.to_owned().into_string().map_err(|s| {
                    format!(
                        "Unable to convert output_files or output_directories due to \
             non UTF-8 characters: {s:?}"
                    )
                })
            })
            .collect::<Result<Vec<_>, _>>()?;

        let (exit_code, stdout, stderr) = Command::new(args)
            .working_dir(working_dir)
            .output(docker, container_id)
            .await?;

        // Failing processes may not create their output files, so we do not treat this as fatal.
        if exit_code != 0 {
            log::debug!(
                "Failed to chmod process outputs in Docker container:\n\
        stdout:\n{}\n\
        stderr:\n{}\n",
                String::from_utf8_lossy(&stdout),
                String::from_utf8_lossy(&stderr)
            );
        }

        Ok(())
    }
}

/// A loose clone of `std::process:Command` for Docker `exec`.
struct Command(bollard::exec::CreateExecOptions<String>);

/// A struct to propagate errors that can occur during the `Command.spawn` method.
struct CommandSpawnError {
    message: String,
    err: DockerError,
}

impl Command {
    fn new(argv: Vec<String>) -> Self {
        Self(bollard::exec::CreateExecOptions {
            cmd: Some(argv),
            attach_stdout: Some(true),
            attach_stderr: Some(true),
            ..bollard::exec::CreateExecOptions::default()
        })
    }

    fn working_dir(&mut self, working_dir: String) -> &mut Self {
        self.0.working_dir = Some(working_dir);
        self
    }

    fn env<I: IntoIterator<Item = (String, String)>>(&mut self, env: I) -> &mut Self {
        self.0.env = Some(
            env.into_iter()
                .map(|(key, value)| format!("{key}={value}"))
                .collect(),
        );
        self
    }

    /// Execute the command that has been specified, and return a stream of ChildOutputs.
    ///
    /// NB: See the TODO on the `ChildOutput` definition.
    async fn spawn<'a, 'b>(
        &'a mut self,
        docker: &'a Docker,
        container_id: String,
    ) -> Result<BoxStream<'b, Result<ChildOutput, String>>, CommandSpawnError> {
        log::trace!("creating execution with config: {:?}", self.0);

        let exec = docker
            .create_exec::<String>(&container_id, self.0.clone())
            .await
            .map_err(|err| CommandSpawnError {
                message: format!("Failed to create Docker execution in container: {err}"),
                err,
            })?;

        log::trace!("created execution {}", &exec.id);

        let exec_result =
            docker
                .start_exec(&exec.id, None)
                .await
                .map_err(|err| CommandSpawnError {
                    message: format!("Failed to start Docker execution `{}`: {}", exec.id, err),
                    err,
                })?;
        let mut output_stream = if let StartExecResults::Attached { output, .. } = exec_result {
            output.boxed()
        } else {
            panic!("Unexpected value returned from start_exec: {exec_result:?}");
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

    /// Execute the command that has been specified, and return its exit code, stdout, and stderr.
    async fn output(
        &mut self,
        docker: &Docker,
        container_id: String,
    ) -> Result<(i32, Bytes, Bytes), CapturedWorkdirError> {
        let child_outputs =
            self.spawn(docker, container_id)
                .await
                .map_err(|cse| match cse.err {
                    // Rather than trying to handle every possible error code, we just restart the container and retry any DockerResponseServerErrors
                    DockerError::DockerResponseServerError { message, .. } => {
                        CapturedWorkdirError::Retryable(message)
                    }
                    _ => CapturedWorkdirError::Fatal(cse.message),
                })?;
        let mut stdout = BytesMut::with_capacity(8192);
        let mut stderr = BytesMut::with_capacity(8192);
        let exit_code = collect_child_outputs(&mut stdout, &mut stderr, child_outputs).await?;
        Ok((exit_code, stdout.freeze(), stderr.freeze()))
    }
}

/// Container ID and NamedCaches for that container. async_oncecell::OnceCell is used so that
/// multiple tasks trying to access an initializing container do not try to start multiple
/// containers.
type CachedContainer = Arc<OnceCell<(String, NamedCaches)>>;

/// Caches running containers so that build actions can be invoked by running "executions"
/// within those cached containers.
pub(crate) struct ContainerCache<'a> {
    docker: &'a DockerOnceCell,
    image_pull_cache: &'a ImagePullCache,
    executor: Executor,
    work_dir_base: String,
    immutable_inputs_base_dir: String,
    /// Cache that maps image name / platform to a cached container.
    pub(crate) containers: Mutex<BTreeMap<(String, Platform), CachedContainer>>,
}

impl<'a> ContainerCache<'a> {
    pub fn new(
        docker: &'a DockerOnceCell,
        image_pull_cache: &'a ImagePullCache,
        executor: Executor,
        work_dir_base: &Path,
        immutable_inputs: &ImmutableInputs,
    ) -> Result<Self, String> {
        let work_dir_base = work_dir_base
            .to_path_buf()
            .into_os_string()
            .into_string()
            .map_err(|s| {
                format!("Unable to convert workdir_path due to non UTF-8 characters: {s:?}")
            })?;

        let immutable_inputs_base_dir = immutable_inputs
            .workdir()
            .to_path_buf()
            .into_os_string()
            .into_string()
            .map_err(|s| {
                format!(
                    "Unable to convert immutable_inputs base dir due to non UTF-8 characters: {s:?}"
                )
            })?;

        Ok(Self {
            docker,
            image_pull_cache,
            executor,
            work_dir_base,
            immutable_inputs_base_dir,
            containers: Mutex::default(),
        })
    }

    /// Creates a container, and creates (if necessary) and attaches a volume for image specific
    /// (named) caches.
    async fn make_container(
        docker: Docker,
        executor: Executor,
        image_name: String,
        platform: Platform,
        image_pull_scope: ImagePullScope,
        image_pull_cache: ImagePullCache,
        work_dir_base: String,
        immutable_inputs_base_dir: String,
        labels: Option<HashMap<String, String>>,
    ) -> Result<String, String> {
        // Pull the image.
        image_pull_cache
            .pull_image(
                &docker,
                &executor,
                &image_name,
                &platform,
                image_pull_scope,
                ImagePullPolicy::OnlyIfLatestOrMissing,
            )
            .await?;

        let named_cache_volume_name = Self::maybe_make_named_cache_volume(&docker, &image_name)
            .await
            .map_err(|e| format!("Failed to create named cache volume for {image_name}: {e}"))?;

        let config = bollard::container::Config {
            entrypoint: Some(vec!["/bin/sh".to_string()]),
            host_config: Some(bollard::service::HostConfig {
                binds: Some(vec![
                    format!("{work_dir_base}:{SANDBOX_BASE_PATH_IN_CONTAINER}"),
                    format!("{named_cache_volume_name}:{NAMED_CACHES_BASE_PATH_IN_CONTAINER}",),
                    // DOCKER-TODO: Consider making this bind mount read-only.
                    format!(
                        "{immutable_inputs_base_dir}:{IMMUTABLE_INPUTS_BASE_PATH_IN_CONTAINER}"
                    ),
                ]),
                // The init process ensures that child processes are properly reaped.
                init: Some(true),
                ..bollard::service::HostConfig::default()
            }),
            image: Some(image_name.clone()),
            tty: Some(true),
            open_stdin: Some(true),
            labels,
            ..bollard::container::Config::default()
        };

        log::trace!("creating cached container with config for image `{image_name}`: {config:?}",);

        let create_options = CreateContainerOptions::<&str> {
            name: "",
            platform: Some(docker_platform_identifier(&platform)),
        };
        let container = docker
            .create_container::<&str, String>(Some(create_options), config)
            .await
            .map_err(|err| format!("Failed to create Docker container: {err:?}"))?;

        docker
            .start_container::<String>(&container.id, None)
            .await
            .map_err(|err| {
                format!(
                    "Failed to start Docker container `{}` for image `{image_name}`: {err:?}",
                    &container.id
                )
            })?;

        log::debug!(
            "started container `{}` for image `{image_name}`",
            &container.id,
        );

        Ok(container.id)
    }

    /// Creates a volume for named caches for the given image name. In production usage, the image
    /// name will have been expanded to include its SHA256 fingerprint, so the named cache will be
    /// dedicated to a particular image version. That is conservative, so we might consider making
    /// it configurable whether the image version is attached in future releases.
    async fn maybe_make_named_cache_volume(
        docker: &Docker,
        image_name: &str,
    ) -> Result<String, DockerError> {
        let image_hash = Digest::of_bytes(image_name.as_bytes())
            .hash
            .to_hex()
            .chars()
            .take(12)
            .collect::<String>();
        let named_cache_volume_name = format!("pants-named-caches-{image_hash}");
        // TODO: Use a filter on volume name.
        let volume_exists = docker
            .list_volumes::<&str>(None)
            .await?
            .volumes
            .map(|volumes| volumes.iter().any(|v| v.name == named_cache_volume_name))
            .unwrap_or(false);
        if volume_exists {
            return Ok(named_cache_volume_name);
        }

        let mut labels = HashMap::new();
        labels.insert("image_name", image_name);
        docker
            .create_volume::<&str>(CreateVolumeOptions {
                name: &named_cache_volume_name,
                driver: "local",
                labels,
                ..CreateVolumeOptions::default()
            })
            .await?;

        Ok(named_cache_volume_name)
    }

    async fn make_named_cache_directory(
        docker: Docker,
        container_id: String,
        directory: PathBuf,
    ) -> Result<(), CapturedWorkdirError> {
        let directory = directory.into_os_string().into_string().map_err(|s| {
            format!(
                "Unable to convert named cache path to string due to non UTF-8 characters: {s:?}"
            )
        })?;
        let (exit_code, stdout, stderr) = Command::new(vec![
            "mkdir".to_owned(),
            "-p".to_owned(),
            directory.to_owned(),
        ])
        .output(&docker, container_id)
        .await?;

        if exit_code == 0 {
            Ok(())
        } else {
            Err(CapturedWorkdirError::Fatal(format!(
                "Failed to create parent directory for named cache in Docker container:\n\
         stdout:\n{}\n\
         stderr:\n{}\n",
                String::from_utf8_lossy(&stdout),
                String::from_utf8_lossy(&stderr)
            )))
        }
    }

    /// Remove an old or missing container from the container cache. Removes the actual container if it still exists.
    pub(crate) async fn prune_container(&self, image_name: &str, platform: &Platform) {
        let maybe_arc = {
            self.containers
                .lock()
                .remove(&(image_name.to_string(), *platform))
        };
        if let Some(container_id) =
            maybe_arc.and_then(|container_once_cell| container_once_cell.get().map(|t| t.0.clone()))
        {
            match self.docker.get().await.cloned() {
                Ok(docker) => {
                    tokio::spawn(async move {
                        let check_state = async {
                            match docker.inspect_container(&container_id, None).await {
                                Ok(ContainerInspectResponse {
                                    state: Some(ContainerState {
                                        status: Some(status @ (ContainerStateStatusEnum::RUNNING
                                            | ContainerStateStatusEnum::RESTARTING
                                            | ContainerStateStatusEnum::CREATED
                                            | ContainerStateStatusEnum::PAUSED)),
                                            ..
                                    }),
                                    ..
                                }) => Err(format!(
                                    "Cannot prune container {container_id} with status {status}"
                                )),
                                Ok(ContainerInspectResponse { state: Some(ContainerState { status: Some(_), .. }), .. }) => Self::remove_container(&docker, &container_id, None)
                                    .await
                                    .map_err(|err| format!(
                                        "An error occurred when trying to remove container {container_id}\n\n{err}"
                                    )),
                                Ok(ContainerInspectResponse { state: Some(ContainerState { status: None, .. }), .. }) => Err(format!(
                                    "Cannot prune container {container_id} with unknown status"
                                )),
                                Ok(ContainerInspectResponse { state: None, .. }) => Err(format!(
                                    "Cannot prune container {container_id}, container state was empty"
                                )),
                                Err(DockerError::DockerResponseServerError {
                                    status_code: 404,
                                    ..
                                }) => Ok(()),
                                Err(err) => Err(format!(
                                    "Cannot prune container {container_id} because the following error occurred when trying to inspect container status:\n\n{err}"
                                )),
                            }
                        };
                        if let Err(msg) = check_state.await {
                            log::warn!("{}", msg);
                        }
                    });
                }
                Err(err) => {
                    log::warn!("Failed to remove container {container_id} due to error:\n\n{err}")
                }
            }
        } else {
            log::warn!(
                "Container for image `{}` and platform `{:#?}` not found",
                image_name,
                platform
            );
        }
    }

    /// Return the container ID and NamedCaches for a container running `image_name` for use as a place
    /// to invoke build actions as executions within the cached container.
    pub async fn container_for_image(
        &self,
        image_name: &str,
        platform: &Platform,
        build_generation: &str,
        environment_name: &str,
    ) -> Result<(String, NamedCaches), String> {
        let docker = self.docker.get().await?.clone();
        let executor = self.executor.clone();

        let container_id_cell = {
            let mut containers = self.containers.lock();
            let cell = containers
                .entry((image_name.to_string(), *platform))
                .or_insert_with(|| Arc::new(OnceCell::new()));
            cell.clone()
        };

        let work_dir_base = self.work_dir_base.clone();
        let immutable_inputs_base_dir = self.immutable_inputs_base_dir.clone();
        let image_pull_scope = ImagePullScope::new(build_generation);

        let container_id = container_id_cell
            .get_or_try_init(async move {
                let container_id = Self::make_container(
                    docker.clone(),
                    executor,
                    image_name.to_string(),
                    *platform,
                    image_pull_scope,
                    self.image_pull_cache.clone(),
                    work_dir_base,
                    immutable_inputs_base_dir,
                    Some(hashmap! {PANTS_CONTAINER_ENVIRONMENT_LABEL_KEY.to_string() => environment_name.to_string()}),
                )
                .await?;

                let named_caches = {
                    let docker = docker.to_owned();
                    let container_id = container_id.clone();
                    NamedCaches::new(NAMED_CACHES_BASE_PATH_IN_CONTAINER.into(), move |dst| {
                        ContainerCache::make_named_cache_directory(
                            docker.clone(),
                            container_id.clone(),
                            dst.to_owned(),
                        )
                        .boxed()
                    })
                };

                Ok::<_, String>((container_id, named_caches))
            })
            .await?;

        Ok(container_id.to_owned())
    }

    pub(crate) async fn remove_container(
        docker: &Docker,
        container_id: &str,
        options: Option<RemoveContainerOptions>,
    ) -> Result<(), DockerError> {
        docker.remove_container(container_id, options).await
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
                ));
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

        let removal_futures = container_ids.into_iter().map(|(id, _)| async move {
            let remove_options = RemoveContainerOptions {
                force: true,
                ..RemoveContainerOptions::default()
            };
            Self::remove_container(docker, id.as_str(), Some(remove_options))
                .await
                .map_err(|err| {
                    format!("Failed to remove Docker container during shutdown `{id}`: {err:?}")
                })
        });
        futures::future::try_join_all(removal_futures).await?;
        Ok(())
    }
}

/// Create a file called __run.sh with Docker commands to facilitate debugging Docker-based executions.
/// This creates a script that starts a Docker container and executes the process within it.
fn setup_docker_run_sh_script(
    sandbox_path: &Path,
    env: &BTreeMap<String, String>,
    working_directory: &Option<RelativePath>,
    argv: &[String],
    workdir_path: &Path,
    image_name: &str,
    host_work_dir_base: &Path,
    host_immutable_inputs_base: &Path,
) -> Result<(), String> {
    // Determine the working directory inside the container
    let container_workdir = {
        let sandbox_relpath = workdir_path
            .strip_prefix(host_work_dir_base)
            .map_err(|err| {
                format!(
                    "Internal error - base directory was not prefix of sandbox directory: {err}"
                )
            })?;
        let sandbox_path_in_container =
            Path::new(SANDBOX_BASE_PATH_IN_CONTAINER).join(sandbox_relpath);

        if let Some(working_directory) = working_directory {
            sandbox_path_in_container.join(working_directory)
        } else {
            sandbox_path_in_container
        }
    };

    let container_workdir_str = container_workdir.to_str().ok_or_else(|| {
        "Unable to convert container working directory to string due to non UTF-8 characters"
            .to_string()
    })?;

    // Format environment variables for Docker
    let mut env_args: Vec<String> = vec![];
    for (key, value) in env.iter() {
        let quoted_value = Bash::quote_vec(value.as_str());
        let value_str = str::from_utf8(&quoted_value)
            .map_err(|e| format!("Error quoting environment variable value: {e:?}"))?
            .to_string();
        env_args.push("-e".to_string());
        env_args.push(format!("{key}={value_str}"));
    }

    // Shell-quote every command-line argument
    let mut quoted_argv: Vec<String> = vec![];
    for arg in argv.iter() {
        let quoted_arg = Bash::quote_vec(arg.as_str());
        let arg_str = str::from_utf8(&quoted_arg)
            .map_err(|e| format!("Error quoting command argument: {e:?}"))?
            .to_string();
        quoted_argv.push(arg_str);
    }

    // Create volume mount arguments
    let host_work_dir_str = host_work_dir_base.to_str().ok_or_else(|| {
        "Unable to convert host work directory to string due to non UTF-8 characters".to_string()
    })?;
    let host_immutable_inputs_str = host_immutable_inputs_base.to_str()
        .ok_or_else(|| "Unable to convert host immutable inputs directory to string due to non UTF-8 characters".to_string())?;

    // Generate named cache volume name (same logic as in make_named_cache_volume)
    let image_hash = hashing::Digest::of_bytes(image_name.as_bytes())
        .hash
        .to_hex()
        .chars()
        .take(12)
        .collect::<String>();
    let named_cache_volume_name = format!("pants-named-caches-{image_hash}");

    let script_content = format!(
        r#"#!/usr/bin/env bash
# This script replicates the Docker-based process execution performed by Pants.
# It starts a container and executes the process within it.

set -euo pipefail

# Ensure required Docker volume exists
if ! docker volume inspect {named_cache_volume_name} >/dev/null 2>&1; then
    echo "Creating Docker volume: {named_cache_volume_name}"
    docker volume create {named_cache_volume_name}
fi

# Start the container if it's not already running
CONTAINER_ID=$(docker run -d \
    --init \
    --tty \
    -v {host_work_dir_str}:{SANDBOX_BASE_PATH_IN_CONTAINER} \
    -v {named_cache_volume_name}:{NAMED_CACHES_BASE_PATH_IN_CONTAINER} \
    -v {host_immutable_inputs_str}:{IMMUTABLE_INPUTS_BASE_PATH_IN_CONTAINER} \
    {image_name} \
    /bin/sh)

echo "Started container: $CONTAINER_ID"

# Ensure container cleanup on script exit
cleanup() {{
    echo "Stopping and removing container: $CONTAINER_ID"
    docker stop "$CONTAINER_ID" >/dev/null 2>&1 || true
    docker rm "$CONTAINER_ID" >/dev/null 2>&1 || true
}}
trap cleanup EXIT

# Execute the command in the container
echo "Executing command in container..."
docker exec \
    -w {container_workdir_str} \
    {env_args} \
    "$CONTAINER_ID" \
    {command_line}
"#,
        named_cache_volume_name = named_cache_volume_name,
        host_work_dir_str = str::from_utf8(&Bash::quote_vec(host_work_dir_str))
            .map_err(|e| format!("Error quoting host work directory: {e:?}"))?,
        host_immutable_inputs_str = str::from_utf8(&Bash::quote_vec(host_immutable_inputs_str))
            .map_err(|e| format!("Error quoting host immutable inputs directory: {e:?}"))?,
        image_name = str::from_utf8(&Bash::quote_vec(image_name))
            .map_err(|e| format!("Error quoting image name: {e:?}"))?,
        container_workdir_str = str::from_utf8(&Bash::quote_vec(container_workdir_str))
            .map_err(|e| format!("Error quoting container working directory: {e:?}"))?,
        env_args = env_args.join(" "),
        command_line = quoted_argv.join(" "),
    );

    let script_path = sandbox_path.join("__run.sh");
    std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(USER_EXECUTABLE_MODE)
        .open(&script_path)
        .map_err(|e| {
            format!(
                "Failed to create Docker run script at {}: {e:?}",
                script_path.display()
            )
        })?
        .write_all(script_content.as_bytes())
        .map_err(|e| format!("Failed to write Docker run script: {e:?}"))
}
