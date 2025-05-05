// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::env;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::Duration;

use async_trait::async_trait;
use bollard::container::RemoveContainerOptions;
use bollard::{Docker, errors::Error as DockerError};
use fs::{EMPTY_DIRECTORY_DIGEST, RelativePath};
use maplit::hashset;
use parameterized::parameterized;
use store::{ImmutableInputs, Store};
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use testutil::{owned_string_vec, relative_paths};
use workunit_store::{RunningWorkunit, WorkunitStore};

use crate::docker::{
    ContainerCache, DockerOnceCell, ImagePullCache, PANTS_CONTAINER_ENVIRONMENT_LABEL_KEY,
    SANDBOX_BASE_PATH_IN_CONTAINER,
};
use process_execution::local::KeepSandboxes;
use process_execution::{
    CacheName, CommandRunner, Context, FallibleProcessResultWithPlatform, InputDigests,
    NamedCaches, Platform, Process, ProcessError, ProcessExecutionStrategy, local,
};

/// Docker image to use for most tests in this file.
const IMAGE: &str = "busybox:1.34.1";

/// Path to `sh` within the image.
const SH_PATH: &str = "/bin/sh";

#[derive(PartialEq, Debug)]
struct LocalTestResult {
    original: FallibleProcessResultWithPlatform,
    stdout_bytes: Vec<u8>,
    stderr_bytes: Vec<u8>,
}

/// Skips a test if Docker is not available in macOS CI.
macro_rules! skip_if_no_docker_available_in_macos_ci {
    () => {{
        let docker = match Docker::connect_with_local_defaults() {
            Ok(docker) => docker,
            Err(err) => {
                if cfg!(target_os = "macos") && env::var_os("GITHUB_ACTIONS").is_some() {
                    println!("Skipping test due to Docker not being available: {:?}", err);
                    return;
                } else {
                    panic!("Docker should have been available for this test: {:?}", err);
                }
            }
        };

        let ping_response = docker.ping().await;
        if ping_response.is_err() {
            if cfg!(target_os = "macos") && env::var_os("GITHUB_ACTIONS").is_some() {
                println!(
                    "Skipping test due to Docker not being available: {:?}",
                    ping_response
                );
                return;
            } else {
                panic!(
                    "Docker should have been available for this test: {:?}",
                    ping_response
                );
            }
        }
    }};
}

fn platform_for_tests() -> Result<Platform, String> {
    Platform::current().map(|platform| match platform {
        Platform::Macos_arm64 => Platform::Linux_arm64,
        Platform::Macos_x86_64 => Platform::Linux_x86_64,
        p => p,
    })
}

async fn assert_container_not_exists(docker: &Docker, container_id: &str) -> Result<(), String> {
    match docker.inspect_container(container_id, None).await {
        Ok(_) => Err(format!(
            "Container {container_id} exists when it should not"
        )),
        Err(DockerError::DockerResponseServerError {
            status_code: 404, ..
        }) => Ok(()),
        Err(err) => Err(format!(
            "An unexpected error {err} occurred when inspecting container {container_id}, which should not exist"
        )),
    }
}

#[async_trait]
trait DockerCommandTestRunner: Send + Sync {
    async fn setup<'a>(
        &self,
        store: Store,
        executor: task_executor::Executor,
        docker: &'a DockerOnceCell,
        image_pull_cache: &'a ImagePullCache,
        work_dir_base: PathBuf,
        immutable_inputs: ImmutableInputs,
    ) -> Result<crate::docker::CommandRunner<'a>, String>;

    async fn assert_correct_container(
        &self,
        docker: &Docker,
        actual_container_id: &str,
    ) -> Result<(), String>;

    async fn run_command_via_docker_in_dir(
        &self,
        mut req: Process,
        dir: PathBuf,
        workunit: &mut RunningWorkunit,
        store: Option<Store>,
        executor: Option<task_executor::Executor>,
    ) -> Result<LocalTestResult, ProcessError> {
        let image =
            if let ProcessExecutionStrategy::Docker(image) = &req.execution_environment.strategy {
                Some(image.clone())
            } else {
                None
            };
        let platform = platform_for_tests().map_err(ProcessError::Unclassified)?;
        req.execution_environment.platform = platform;
        req.execution_environment.name = Some("test".to_string());
        let store_dir = TempDir::new().unwrap();
        let executor = executor.unwrap_or_else(task_executor::Executor::new);
        let store =
            store.unwrap_or_else(|| Store::local_only(executor.clone(), store_dir.path()).unwrap());

        let root = TempDir::new().unwrap();
        let root_path = root.path().to_owned();

        let immutable_inputs = ImmutableInputs::new(store.clone(), &root_path).unwrap();

        let docker = Box::new(DockerOnceCell::new());
        let image_pull_cache = Box::new(ImagePullCache::new());
        let runner = self
            .setup(
                store.clone(),
                executor.clone(),
                &docker,
                &image_pull_cache,
                dir.clone(),
                immutable_inputs,
            )
            .await?;
        let result: Result<_, ProcessError> = async {
            let original = runner.run(Context::default(), workunit, req).await?;
            let stdout_bytes = store
                .load_file_bytes_with(original.stdout_digest, |bytes| bytes.to_vec())
                .await?;
            let stderr_bytes = store
                .load_file_bytes_with(original.stderr_digest, |bytes| bytes.to_vec())
                .await?;
            Ok((original, stdout_bytes, stderr_bytes))
        }
        .await;
        let (original, stdout_bytes, stderr_bytes) = result?;
        let container_id = {
            let containers = runner.container_cache.containers.lock();
            assert_eq!(containers.len(), 1);
            if let Some(((actual_image, actual_platform), value_arc)) = containers.first_key_value()
            {
                assert_eq!(*actual_image, image.unwrap());
                assert_eq!(*actual_platform, platform);
                assert!(value_arc.initialized());
                value_arc.get().unwrap().0.clone()
            } else {
                unreachable!("we know we have the entry")
            }
        };
        let docker_ref = docker.get().await?;
        self.assert_correct_container(docker_ref, &container_id)
            .await?;
        match docker_ref
            .inspect_container(&container_id, None)
            .await
            .map_err(|err| ProcessError::Unclassified(err.to_string()))?
            .config
            .unwrap()
            .labels
        {
            Some(labels) => assert_eq!(labels[PANTS_CONTAINER_ENVIRONMENT_LABEL_KEY], "test"),
            None => panic!("No labels found for container {container_id}"),
        }
        runner.shutdown().await?;
        assert_container_not_exists(docker_ref, &container_id).await?;
        Ok(LocalTestResult {
            original,
            stdout_bytes,
            stderr_bytes,
        })
    }

    async fn run_command_via_docker(&self, req: Process) -> Result<LocalTestResult, ProcessError> {
        let (_, mut workunit) = WorkunitStore::setup_for_tests();
        let work_dir = TempDir::new().unwrap();
        let work_dir_path = work_dir.path().to_owned();
        self.run_command_via_docker_in_dir(req, work_dir_path, &mut workunit, None, None)
            .await
    }
}

struct DefaultTestRunner;

#[async_trait]
impl DockerCommandTestRunner for DefaultTestRunner {
    async fn setup<'a>(
        &self,
        store: Store,
        executor: task_executor::Executor,
        docker: &'a DockerOnceCell,
        image_pull_cache: &'a ImagePullCache,
        work_dir_base: PathBuf,
        immutable_inputs: ImmutableInputs,
    ) -> Result<crate::docker::CommandRunner<'a>, String> {
        crate::docker::CommandRunner::new(
            store,
            executor,
            docker,
            image_pull_cache,
            work_dir_base,
            immutable_inputs,
        )
    }

    async fn assert_correct_container(
        &self,
        _docker: &Docker,
        _actual_container_id: &str,
    ) -> Result<(), String> {
        Ok(())
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
#[cfg(unix)]
async fn runner_errors_if_docker_image_not_set() {
    skip_if_no_docker_available_in_macos_ci!();

    let runner = DefaultTestRunner;
    // Because `docker_image` is set but it does not exist, this process should fail.
    let err = runner
        .run_command_via_docker(
            Process::new(owned_string_vec(&["/bin/echo", "-n", "foo"]))
                .docker("does-not-exist:latest".to_owned()),
        )
        .await
        .unwrap_err();
    if let ProcessError::Unclassified(msg) = err {
        assert!(msg.contains("Failed to pull Docker image"));
    } else {
        panic!("unexpected value: {err:?}")
    }

    // Otherwise, if docker_image is not set, use the local runner.
    let err = runner
        .run_command_via_docker(Process::new(owned_string_vec(&["/bin/echo", "-n", "foo"])))
        .await
        .unwrap_err();
    if let ProcessError::Unclassified(msg) = &err {
        assert!(
      msg.contains("The Docker execution strategy was not set on the Process, but the Docker CommandRunner was used")
    );
    } else {
        panic!("unexpected value: {err:?}")
    }
}

struct ExistingContainerTestRunner {
    image_name: String,
    platform: Platform,
    container_id: OnceLock<(String, NamedCaches)>,
}

impl ExistingContainerTestRunner {
    fn new(image_name: &str) -> Self {
        ExistingContainerTestRunner {
            image_name: image_name.to_string(),
            platform: platform_for_tests().unwrap(),
            container_id: OnceLock::new(),
        }
    }

    fn get_container_id(&self) -> String {
        self.container_id.get().unwrap().0.clone()
    }
}

#[async_trait]
impl DockerCommandTestRunner for ExistingContainerTestRunner {
    async fn setup<'a>(
        &self,
        store: Store,
        executor: task_executor::Executor,
        docker: &'a DockerOnceCell,
        image_pull_cache: &'a ImagePullCache,
        work_dir_base: PathBuf,
        immutable_inputs: ImmutableInputs,
    ) -> Result<crate::docker::CommandRunner<'a>, String> {
        let command_runner = crate::docker::CommandRunner::new(
            store,
            executor,
            docker,
            image_pull_cache,
            work_dir_base,
            immutable_inputs,
        )?;
        match self.container_id.set(
            command_runner
                .container_cache
                .container_for_image(&self.image_name, &self.platform, "", "test")
                .await?,
        ) {
            Ok(()) => Ok(command_runner),
            Err(_) => Err("An error occurred when attempting to save container ID".to_string()),
        }
    }

    async fn assert_correct_container(
        &self,
        _docker: &Docker,
        actual_container_id: &str,
    ) -> Result<(), String> {
        assert_eq!(self.get_container_id(), actual_container_id);
        Ok(())
    }
}

#[async_trait]
trait UnavailableContainerTestRunner: DockerCommandTestRunner {
    async fn get_command_runner<'a>(
        &self,
        store: Store,
        executor: task_executor::Executor,
        docker: &'a DockerOnceCell,
        image_pull_cache: &'a ImagePullCache,
        work_dir_base: PathBuf,
        immutable_inputs: ImmutableInputs,
    ) -> Result<crate::docker::CommandRunner<'a>, String>;

    async fn make_container_unavailable(&self, docker: &Docker) -> Result<(), String>;

    fn get_initial_container_id(&self) -> String;
}

#[async_trait]
impl<T: UnavailableContainerTestRunner> DockerCommandTestRunner for T {
    async fn setup<'a>(
        &self,
        store: Store,
        executor: task_executor::Executor,
        docker: &'a DockerOnceCell,
        image_pull_cache: &'a ImagePullCache,
        work_dir_base: PathBuf,
        immutable_inputs: ImmutableInputs,
    ) -> Result<crate::docker::CommandRunner<'a>, String> {
        let command_runner = self
            .get_command_runner(
                store,
                executor,
                docker,
                image_pull_cache,
                work_dir_base,
                immutable_inputs,
            )
            .await?;
        let docker_ref = docker.get().await?;
        self.make_container_unavailable(docker_ref).await?;
        Ok(command_runner)
    }

    async fn assert_correct_container(
        &self,
        docker: &Docker,
        actual_container_id: &str,
    ) -> Result<(), String> {
        let initial_container_id = self.get_initial_container_id();
        assert_ne!(initial_container_id, actual_container_id);
        // Check and ensure initial container was cleaned up
        assert_container_not_exists(docker, &initial_container_id).await
    }
}

struct MissingContainerTestRunner {
    inner: ExistingContainerTestRunner,
}

impl MissingContainerTestRunner {
    fn new(image_name: &str) -> Self {
        MissingContainerTestRunner {
            inner: ExistingContainerTestRunner::new(image_name),
        }
    }
}

#[async_trait]
impl UnavailableContainerTestRunner for MissingContainerTestRunner {
    async fn get_command_runner<'a>(
        &self,
        store: Store,
        executor: task_executor::Executor,
        docker: &'a DockerOnceCell,
        image_pull_cache: &'a ImagePullCache,
        work_dir_base: PathBuf,
        immutable_inputs: ImmutableInputs,
    ) -> Result<crate::docker::CommandRunner<'a>, String> {
        self.inner
            .setup(
                store,
                executor,
                docker,
                image_pull_cache,
                work_dir_base,
                immutable_inputs,
            )
            .await
    }

    async fn make_container_unavailable(&self, docker: &Docker) -> Result<(), String> {
        let container_id = self.inner.container_id.get().unwrap().0.as_str();
        ContainerCache::remove_container(
            docker,
            container_id,
            Some(RemoveContainerOptions {
                force: true,
                ..RemoveContainerOptions::default()
            }),
        )
        .await
        .map_err(|err| {
            format!("Failed to remove Docker container during missing container test setup `{container_id}`: {err:?}")
        })
    }

    fn get_initial_container_id(&self) -> String {
        self.inner.get_container_id()
    }
}

struct ExitedContainerTestRunner {
    inner: ExistingContainerTestRunner,
}

impl ExitedContainerTestRunner {
    fn new(image_name: &str) -> Self {
        ExitedContainerTestRunner {
            inner: ExistingContainerTestRunner::new(image_name),
        }
    }
}

#[async_trait]
impl UnavailableContainerTestRunner for ExitedContainerTestRunner {
    async fn get_command_runner<'a>(
        &self,
        store: Store,
        executor: task_executor::Executor,
        docker: &'a DockerOnceCell,
        image_pull_cache: &'a ImagePullCache,
        work_dir_base: PathBuf,
        immutable_inputs: ImmutableInputs,
    ) -> Result<crate::docker::CommandRunner<'a>, String> {
        self.inner
            .setup(
                store,
                executor,
                docker,
                image_pull_cache,
                work_dir_base,
                immutable_inputs,
            )
            .await
    }

    async fn make_container_unavailable(&self, docker: &Docker) -> Result<(), String> {
        let container_id = self.inner.container_id.get().unwrap().0.as_str();
        docker.stop_container(container_id, None)
            .await
            .map_err(|err| format!("An error occurred when trying to kill running container {container_id}:\n\n{err}"))?;
        Ok(())
    }

    fn get_initial_container_id(&self) -> String {
        self.inner.get_container_id()
    }
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
#[cfg(unix)]
async fn stdout(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();
    let result = runner
        .run_command_via_docker(
            Process::new(owned_string_vec(&["/bin/echo", "-n", "foo"])).docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "foo".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
#[cfg(unix)]
async fn stdout_and_stderr_and_exit_code(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();
    let result = runner
        .run_command_via_docker(
            Process::new(owned_string_vec(&[
                SH_PATH,
                "-c",
                "echo -n foo ; echo >&2 -n bar ; exit 1",
            ]))
            .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "foo".as_bytes());
    assert_eq!(result.stderr_bytes, "bar".as_bytes());
    assert_eq!(result.original.exit_code, 1);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
#[cfg(unix)]
async fn capture_exit_code_signal(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    // Launch a process that kills itself with a signal.
    let result = runner
        .run_command_via_docker(
            Process::new(owned_string_vec(&[SH_PATH, "-c", "kill $$"])).docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    // DOCKER-TODO: Figure out a way to capture the signal from the container. Docker does not
    // seem to make that available. The `143` code comes from the init process in the container.
    // assert_eq!(result.original.exit_code, -15);
    assert_eq!(result.original.exit_code, 143);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

fn extract_env(
    content: Vec<u8>,
    exclude_keys: &[&str],
) -> Result<BTreeMap<String, String>, String> {
    let content =
        String::from_utf8(content).map_err(|_| "Invalid UTF-8 in env output".to_string())?;
    let result = content
        .split('\n')
        .filter(|line| !line.is_empty())
        .map(|line| line.splitn(2, '='))
        .map(|mut parts| {
            (
                parts.next().unwrap().to_string(),
                parts.next().unwrap_or("").to_string(),
            )
        })
        .filter(|x| !exclude_keys.iter().any(|&k| k == x.0))
        .collect();
    Ok(result)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
#[cfg(unix)]
async fn env() {
    skip_if_no_docker_available_in_macos_ci!();

    let mut env: BTreeMap<String, String> = BTreeMap::new();
    env.insert("FOO".to_string(), "foo".to_string());
    env.insert("BAR".to_string(), "not foo".to_string());

    let result = DefaultTestRunner
        .run_command_via_docker(
            Process::new(owned_string_vec(&["/bin/env"]))
                .env(env.clone())
                .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    let exclude_keys = &["PATH", "HOME", "HOSTNAME"];
    let got_env = extract_env(result.stdout_bytes, exclude_keys).unwrap();
    assert_eq!(env, got_env);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
#[cfg(unix)]
async fn env_is_deterministic() {
    skip_if_no_docker_available_in_macos_ci!();

    fn make_request() -> Process {
        let mut env = BTreeMap::new();
        env.insert("FOO".to_string(), "foo".to_string());
        env.insert("BAR".to_string(), "not foo".to_string());
        Process::new(owned_string_vec(&["/bin/env"]))
            .env(env)
            .docker(IMAGE.to_owned())
    }

    let result1 = DefaultTestRunner
        .run_command_via_docker(make_request())
        .await
        .unwrap();
    let result2 = DefaultTestRunner
        .run_command_via_docker(make_request())
        .await
        .unwrap();

    let exclude_keys = &["PATH", "HOME", "HOSTNAME"];
    let env1 = extract_env(result1.stdout_bytes, exclude_keys).unwrap();
    let env2 = extract_env(result2.stdout_bytes, exclude_keys).unwrap();
    assert_eq!(env1, env2);
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn binary_not_found(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    // Use `xyzzy` as a command that should not exist.
    let result = runner
        .run_command_via_docker(
            Process::new(owned_string_vec(&["xyzzy", "-n", "foo"])).docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();
    let stdout = String::from_utf8(result.stdout_bytes).unwrap();
    assert!(stdout.contains("exec failed"));
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn output_files_none(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner
        .run_command_via_docker(
            Process::new(owned_string_vec(&[SH_PATH, "-c", "exit 0"])).docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn output_files_one(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner
        .run_command_via_docker(
            Process::new(vec![
                SH_PATH.to_string(),
                "-c".to_owned(),
                format!("echo -n {} > roland.ext", TestData::roland().string()),
            ])
            .output_files(relative_paths(&["roland.ext"]).collect())
            .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::containing_roland().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn output_dirs(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner
        .run_command_via_docker(
            Process::new(vec![
                SH_PATH.to_string(),
                "-c".to_owned(),
                format!(
                    "/bin/mkdir cats && echo -n {} > cats/roland.ext ; echo -n {} > treats.ext",
                    TestData::roland().string(),
                    TestData::catnip().string()
                ),
            ])
            .output_files(relative_paths(&["treats.ext"]).collect())
            .output_directories(relative_paths(&["cats"]).collect())
            .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::recursive().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn output_files_many(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner
        .run_command_via_docker(
            Process::new(vec![
                SH_PATH.to_string(),
                "-c".to_owned(),
                format!(
                    "echo -n {} > cats/roland.ext ; echo -n {} > treats.ext",
                    TestData::roland().string(),
                    TestData::catnip().string()
                ),
            ])
            .output_files(relative_paths(&["cats/roland.ext", "treats.ext"]).collect())
            .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::recursive().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn output_files_execution_failure(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner
        .run_command_via_docker(
            Process::new(vec![
                SH_PATH.to_string(),
                "-c".to_owned(),
                format!(
                    "echo -n {} > roland.ext ; exit 1",
                    TestData::roland().string()
                ),
            ])
            .output_files(relative_paths(&["roland.ext"]).collect())
            .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 1);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::containing_roland().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn output_files_partial_output(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner
        .run_command_via_docker(
            Process::new(vec![
                SH_PATH.to_string(),
                "-c".to_owned(),
                format!("echo -n {} > roland.ext", TestData::roland().string()),
            ])
            .output_files(relative_paths(&["roland.ext", "susannah"]).collect())
            .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::containing_roland().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn output_overlapping_file_and_dir(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner
        .run_command_via_docker(
            Process::new(vec![
                SH_PATH.to_string(),
                "-c".to_owned(),
                format!("echo -n {} > cats/roland.ext", TestData::roland().string()),
            ])
            .output_files(relative_paths(&["cats/roland.ext"]).collect())
            .output_directories(relative_paths(&["cats"]).collect())
            .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::nested().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn append_only_cache_created(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let name = "geo";
    let dest_base = ".cache";
    let cache_name = CacheName::new(name.to_owned()).unwrap();
    let cache_dest = RelativePath::new(format!("{dest_base}/{name}")).unwrap();
    let result = runner
        .run_command_via_docker(
            Process::new(owned_string_vec(&["/bin/ls", dest_base]))
                .append_only_caches(vec![(cache_name, cache_dest)].into_iter().collect())
                .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, format!("{name}\n").as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
#[cfg(unix)]
async fn test_apply_chroot() {
    let mut env: BTreeMap<String, String> = BTreeMap::new();
    env.insert("PATH".to_string(), "/usr/bin:{chroot}/bin".to_string());

    let work_dir = TempDir::new().unwrap();
    let mut req = Process::new(owned_string_vec(&["/usr/bin/env"]))
        .env(env.clone())
        .docker(IMAGE.to_owned());
    local::apply_chroot(work_dir.path().to_str().unwrap(), &mut req);

    let path = format!("/usr/bin:{}/bin", work_dir.path().to_str().unwrap());

    assert_eq!(&path, req.env.get(&"PATH".to_string()).unwrap());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
async fn test_chroot_placeholder() {
    skip_if_no_docker_available_in_macos_ci!();

    let (_, mut workunit) = WorkunitStore::setup_for_tests();
    let mut env: BTreeMap<String, String> = BTreeMap::new();
    env.insert("PATH".to_string(), "/usr/bin:{chroot}/bin".to_string());

    let work_tmpdir = TempDir::new().unwrap();
    let work_root = work_tmpdir.path().to_owned();

    let result = DefaultTestRunner
        .run_command_via_docker_in_dir(
            Process::new(vec!["/bin/env".to_owned()])
                .env(env.clone())
                .docker(IMAGE.to_owned())
                .local_keep_sandboxes(KeepSandboxes::Always),
            work_root.clone(),
            &mut workunit,
            None,
            None,
        )
        .await
        .unwrap();

    let got_env = extract_env(result.stdout_bytes, &[]).unwrap();
    let path = format!("/usr/bin:{SANDBOX_BASE_PATH_IN_CONTAINER}");
    assert!(got_env.get(&"PATH".to_string()).unwrap().starts_with(&path));
    assert!(got_env.get(&"PATH".to_string()).unwrap().ends_with("/bin"));
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn all_containing_directories_for_outputs_are_created(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner
        .run_command_via_docker(
            Process::new(vec![
                SH_PATH.to_string(),
                "-c".to_owned(),
                format!(
                    // mkdir would normally fail, since birds/ doesn't yet exist, as would echo, since cats/
                    // does not exist, but we create the containing directories for all outputs before the
                    // process executes.
                    "/bin/mkdir birds/falcons && echo -n {} > cats/roland.ext",
                    TestData::roland().string()
                ),
            ])
            .output_files(relative_paths(&["cats/roland.ext"]).collect())
            .output_directories(relative_paths(&["birds/falcons"]).collect())
            .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::nested_dir_and_file().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn outputs_readable_only_by_container_user_are_captured(
    runner: &dyn DockerCommandTestRunner,
) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner.run_command_via_docker(
        Process::new(vec![
            SH_PATH.to_string(),
            "-c".to_owned(),
            format!(
        // Ensure that files are only readable by the container user (which on Linux would usually
        // mean that a non-root user outside the container would not have access).
        "/bin/mkdir birds/falcons && echo -n {} > cats/roland.ext && chmod o-r -R birds cats",
        TestData::roland().string()
      ),
        ])
        .output_files(relative_paths(&["cats/roland.ext"]).collect())
        .output_directories(relative_paths(&["birds/falcons"]).collect())
        .docker(IMAGE.to_owned()),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::nested_dir_and_file().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn output_empty_dir(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let result = runner
        .run_command_via_docker(
            Process::new(vec![
                SH_PATH.to_string(),
                "-c".to_owned(),
                "/bin/mkdir falcons".to_string(),
            ])
            .output_directories(relative_paths(&["falcons"]).collect())
            .docker(IMAGE.to_owned()),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::containing_falcons_dir().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn timeout(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();

    let argv = vec![
        SH_PATH.to_string(),
        "-c".to_owned(),
        "/bin/echo -n 'Calculating...'; /bin/sleep 5; /bin/echo -n 'European Burmese'".to_string(),
    ];

    let mut process = Process::new(argv).docker(IMAGE.to_owned());
    process.timeout = Some(Duration::from_millis(500));
    process.description = "sleepy-cat".to_string();

    let result = runner.run_command_via_docker(process).await.unwrap();

    assert_eq!(result.original.exit_code, -15);
    let stdout = String::from_utf8(result.stdout_bytes.to_vec()).unwrap();
    let stderr = String::from_utf8(result.stderr_bytes.to_vec()).unwrap();
    assert!(&stdout.contains("Calculating..."));
    assert!(&stderr.contains("Exceeded timeout"));
    assert!(&stderr.contains("sleepy-cat"));
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn working_directory(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let store_dir = TempDir::new().unwrap();
    let executor = task_executor::Executor::new();
    let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

    // Prepare the store to contain /cats/roland.ext, because the EPR needs to materialize it and
    // then run from the ./cats directory.
    store
        .store_file_bytes(TestData::roland().bytes(), false)
        .await
        .expect("Error saving file bytes");
    store
        .record_directory(&TestDirectory::containing_roland().directory(), true)
        .await
        .expect("Error saving directory");
    store
        .record_directory(&TestDirectory::nested().directory(), true)
        .await
        .expect("Error saving directory");

    let work_dir = TempDir::new().unwrap();

    let mut process = Process::new(vec![
        SH_PATH.to_string(),
        "-c".to_owned(),
        "/bin/ls".to_string(),
    ])
    .docker(IMAGE.to_owned());
    process.working_directory = Some(RelativePath::new("cats").unwrap());
    process.output_directories = relative_paths(&["roland.ext"]).collect::<BTreeSet<_>>();
    process.input_digests =
        InputDigests::with_input_files(TestDirectory::nested().directory_digest());
    process.timeout = Some(Duration::from_secs(1));
    process.description = "confused-cat".to_string();

    let result = runner
        .run_command_via_docker_in_dir(
            process,
            work_dir.path().to_owned(),
            &mut workunit,
            Some(store),
            Some(executor),
        )
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "roland.ext\n".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::containing_roland().directory_digest()
    );
}

#[parameterized(runner = {&DefaultTestRunner, &ExistingContainerTestRunner::new(IMAGE), &MissingContainerTestRunner::new(IMAGE), &ExitedContainerTestRunner::new(IMAGE)}, name = {"default", "existing", "missing", "exited"})]
#[parameterized_macro(tokio::test(flavor = "multi_thread", worker_threads = 1))]
async fn immutable_inputs(runner: &dyn DockerCommandTestRunner) {
    skip_if_no_docker_available_in_macos_ci!();
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let store_dir = TempDir::new().unwrap();
    let executor = task_executor::Executor::new();
    let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

    store
        .store_file_bytes(TestData::roland().bytes(), false)
        .await
        .expect("Error saving file bytes");
    store
        .record_directory(&TestDirectory::containing_roland().directory(), true)
        .await
        .expect("Error saving directory");
    store
        .record_directory(&TestDirectory::containing_falcons_dir().directory(), true)
        .await
        .expect("Error saving directory");

    let work_dir = TempDir::new().unwrap();

    let mut process = Process::new(vec![
        SH_PATH.to_string(),
        "-c".to_owned(),
        "/bin/ls".to_string(),
    ])
    .docker(IMAGE.to_owned());
    process.input_digests = InputDigests::new(
        &store,
        TestDirectory::containing_falcons_dir().directory_digest(),
        {
            let mut map = BTreeMap::new();
            map.insert(
                RelativePath::new("cats").unwrap(),
                TestDirectory::containing_roland().directory_digest(),
            );
            map
        },
        BTreeSet::default(),
    )
    .await
    .unwrap();
    process.timeout = Some(Duration::from_secs(1));
    process.description = "confused-cat".to_string();

    let result = runner
        .run_command_via_docker_in_dir(
            process,
            work_dir.path().to_owned(),
            &mut workunit,
            Some(store),
            Some(executor),
        )
        .await
        .unwrap();

    let stdout_lines = std::str::from_utf8(&result.stdout_bytes)
        .unwrap()
        .lines()
        .collect::<HashSet<_>>();
    assert_eq!(stdout_lines, hashset! {"falcons", "cats"});
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
}
