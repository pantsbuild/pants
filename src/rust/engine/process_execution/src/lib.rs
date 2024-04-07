// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#[macro_use]
extern crate derivative;

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::convert::TryFrom;
use std::fmt::{self, Debug, Display};
use std::path::PathBuf;
use std::sync::Arc;

use async_trait::async_trait;
use bytes::Bytes;
use concrete_time::{Duration, TimeSpan};
use deepsize::DeepSizeOf;
use fs::{DirectoryDigest, RelativePath, EMPTY_DIRECTORY_DIGEST};
use fs::{File, PathStat};
use futures::future::try_join_all;
use futures::future::{self, BoxFuture, TryFutureExt};
use futures::try_join;
use futures::FutureExt;
use grpc_util::prost::MessageExt;
use hashing::Digest;
use itertools::Itertools;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::require_digest;
use remexec::ExecutedActionMetadata;
use remexec::{Action, Command, ExecuteRequest};
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::HashMap;
use std::fmt::Write;
use std::path::Path;
use store::{Snapshot, StoreFileByDigest};
use store::{SnapshotOps, Store, StoreError};
use task_executor::TailTasks;
use tryfuture::try_future;
use uuid::Uuid;
use workunit_store::{in_workunit, Level, RunId, RunningWorkunit, WorkunitStore};

pub mod bounded;
#[cfg(test)]
mod bounded_tests;

pub mod cache;
#[cfg(test)]
mod cache_tests;

pub mod switched;

pub mod children;

pub mod local;
#[cfg(test)]
pub mod local_tests;

pub mod named_caches;
#[cfg(test)]
pub mod named_caches_tests;

pub(crate) mod fork_exec;

pub mod workspace;

extern crate uname;

pub use crate::children::ManagedChild;
pub use crate::named_caches::{CacheName, NamedCaches};

// Environment variable which is exclusively used for cache key invalidation.
// This may be not specified in an Process, and may be populated only by the
// CommandRunner.
pub const CACHE_KEY_GEN_VERSION_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_GEN_VERSION";

// Environment variable which is used to differentiate between running in Docker vs. local vs.
// remote execution.
pub const CACHE_KEY_EXECUTION_STRATEGY: &str = "PANTS_CACHE_KEY_EXECUTION_STRATEGY";

// Environment variable which is used to include a unique value for cache busting of processes that
// have indicated that they should never be cached.
pub const CACHE_KEY_SALT_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_SALT";

// Environment variable which is exclusively used for cache key invalidation.
// This may be not specified in an Process, and may be populated only by the
// CommandRunner.
pub const CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_TARGET_PLATFORM";

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProcessError {
    /// A Digest was not present in either of the local or remote Stores.
    MissingDigest(String, Digest),
    /// All other error types.
    Unclassified(String),
}

impl ProcessError {
    pub fn enrich(self, prefix: &str) -> Self {
        match self {
            Self::MissingDigest(s, d) => Self::MissingDigest(format!("{prefix}: {s}"), d),
            Self::Unclassified(s) => Self::Unclassified(format!("{prefix}: {s}")),
        }
    }
}

impl Display for ProcessError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingDigest(s, d) => {
                write!(f, "{s}: {d:?}")
            }
            Self::Unclassified(s) => write!(f, "{s}"),
        }
    }
}

impl From<StoreError> for ProcessError {
    fn from(err: StoreError) -> Self {
        match err {
            StoreError::MissingDigest(s, d) => Self::MissingDigest(s, d),
            StoreError::Unclassified(s) => Self::Unclassified(s),
        }
    }
}

impl From<String> for ProcessError {
    fn from(err: String) -> Self {
        Self::Unclassified(err)
    }
}

#[derive(
    PartialOrd, Ord, Clone, Copy, Debug, DeepSizeOf, Eq, PartialEq, Hash, Serialize, Deserialize,
)]
#[allow(non_camel_case_types)]
pub enum Platform {
    Macos_x86_64,
    Macos_arm64,
    Linux_x86_64,
    Linux_arm64,
}

impl Platform {
    pub fn current() -> Result<Platform, String> {
        let platform_info =
            uname::uname().map_err(|_| "Failed to get local platform info!".to_string())?;
        match platform_info {
            uname::Info {
                ref sysname,
                ref machine,
                ..
            } if sysname.to_lowercase() == "linux" && machine.to_lowercase() == "x86_64" => {
                Ok(Platform::Linux_x86_64)
            }
            uname::Info {
                ref sysname,
                ref machine,
                ..
            } if sysname.to_lowercase() == "linux"
                && (machine.to_lowercase() == "arm64" || machine.to_lowercase() == "aarch64") =>
            {
                Ok(Platform::Linux_arm64)
            }
            uname::Info {
                ref sysname,
                ref machine,
                ..
            } if sysname.to_lowercase() == "darwin" && machine.to_lowercase() == "arm64" => {
                Ok(Platform::Macos_arm64)
            }
            uname::Info {
                ref sysname,
                ref machine,
                ..
            } if sysname.to_lowercase() == "darwin" && machine.to_lowercase() == "x86_64" => {
                Ok(Platform::Macos_x86_64)
            }
            uname::Info {
                ref sysname,
                ref machine,
                ..
            } => Err(format!(
                "Found unknown system/arch name pair {sysname} {machine}"
            )),
        }
    }
}

impl From<Platform> for String {
    fn from(platform: Platform) -> String {
        match platform {
            Platform::Linux_x86_64 => "linux_x86_64".to_string(),
            Platform::Linux_arm64 => "linux_arm64".to_string(),
            Platform::Macos_arm64 => "macos_arm64".to_string(),
            Platform::Macos_x86_64 => "macos_x86_64".to_string(),
        }
    }
}

impl TryFrom<String> for Platform {
    type Error = String;
    fn try_from(variant_candidate: String) -> Result<Self, Self::Error> {
        match variant_candidate.as_ref() {
            "macos_arm64" => Ok(Platform::Macos_arm64),
            "macos_x86_64" => Ok(Platform::Macos_x86_64),
            "linux_x86_64" => Ok(Platform::Linux_x86_64),
            "linux_arm64" => Ok(Platform::Linux_arm64),
            other => Err(format!("Unknown platform {other:?} encountered in parsing")),
        }
    }
}

#[derive(Clone, Copy, Debug, DeepSizeOf, Eq, PartialEq, Hash, Serialize)]
pub enum ProcessCacheScope {
    // Cached in all locations, regardless of success or failure.
    Always,
    // Cached in all locations, but only if the process exits successfully.
    Successful,
    // Cached only in memory (i.e. memoized in pantsd), but never persistently, regardless of
    // success vs. failure.
    PerRestartAlways,
    // Cached only in memory (i.e. memoized in pantsd), but never persistently, and only if
    // successful.
    PerRestartSuccessful,
    // Will run once per Session, i.e. once per run of Pants. This happens because the engine
    // de-duplicates identical work; the process is neither memoized in memory nor cached to disk.
    PerSession,
}

impl TryFrom<String> for ProcessCacheScope {
    type Error = String;
    fn try_from(variant_candidate: String) -> Result<Self, Self::Error> {
        match variant_candidate.to_lowercase().as_ref() {
            "always" => Ok(ProcessCacheScope::Always),
            "successful" => Ok(ProcessCacheScope::Successful),
            "per_restart_always" => Ok(ProcessCacheScope::PerRestartAlways),
            "per_restart_successful" => Ok(ProcessCacheScope::PerRestartSuccessful),
            "per_session" => Ok(ProcessCacheScope::PerSession),
            other => Err(format!("Unknown Process cache scope: {other:?}")),
        }
    }
}

fn serialize_level<S: serde::Serializer>(level: &log::Level, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&level.to_string())
}

/// Input Digests for a process execution.
///
/// The `complete` and `nailgun` Digests are the computed union of various inputs.
///
/// TODO: See `crate::local::prepare_workdir` regarding validation of overlapping inputs.
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq, Serialize)]
pub struct InputDigests {
    /// All of the input Digests, merged and relativized. Runners without the ability to consume the
    /// Digests individually should directly consume this value.
    pub complete: DirectoryDigest,

    /// The merged Digest of any `use_nailgun`-relevant Digests.
    pub nailgun: DirectoryDigest,

    /// The input files for the process execution, which will be materialized as mutable inputs in a
    /// sandbox for the process.
    ///
    pub inputs: DirectoryDigest,

    /// Immutable input digests to make available in the input root.
    ///
    /// These digests are intended for inputs that will be reused between multiple Process
    /// invocations, without being mutated. This might be useful to provide the tools being executed,
    /// but can also be used for tool inputs such as compilation artifacts.
    ///
    /// The digests will be mounted at the relative path represented by the `RelativePath` keys.
    /// The executor may choose how to make the digests available, including by just merging
    /// the digest normally into the input root, creating a symlink to a persistent cache,
    /// or bind mounting the directory read-only into a persistent cache. Consequently, the mount
    /// point of each input must not overlap the `input_files`, even for directory entries.
    ///
    /// Assumes the build action does not modify the Digest as made available. This may be
    /// enforced by an executor, for example by bind mounting the directory read-only.
    pub immutable_inputs: BTreeMap<RelativePath, DirectoryDigest>,

    /// If non-empty, use nailgun in supported runners, using the specified `immutable_inputs` keys
    /// as server inputs. All other keys (and the input_files) will be client inputs.
    pub use_nailgun: BTreeSet<RelativePath>,
}

impl InputDigests {
    pub async fn new(
        store: &Store,
        inputs: DirectoryDigest,
        immutable_inputs: BTreeMap<RelativePath, DirectoryDigest>,
        use_nailgun: BTreeSet<RelativePath>,
    ) -> Result<Self, StoreError> {
        // Collect all digests into `complete`.
        let mut complete_digests = try_join_all(
            immutable_inputs
                .iter()
                .map(|(path, digest)| store.add_prefix(digest.clone(), path))
                .collect::<Vec<_>>(),
        )
        .await?;
        // And collect only the subset of the Digests which impact nailgun into `nailgun`.
        let nailgun_digests = immutable_inputs
            .keys()
            .zip(complete_digests.iter())
            .filter_map(|(path, digest)| {
                if use_nailgun.contains(path) {
                    Some(digest.clone())
                } else {
                    None
                }
            })
            .collect::<Vec<_>>();
        complete_digests.push(inputs.clone());

        let (complete, nailgun) =
            try_join!(store.merge(complete_digests), store.merge(nailgun_digests),)?;
        Ok(Self {
            complete,
            nailgun,
            inputs,
            immutable_inputs,
            use_nailgun,
        })
    }

    pub async fn new_from_merged(
        store: &Store,
        from: Vec<InputDigests>,
    ) -> Result<Self, StoreError> {
        let mut merged_immutable_inputs = BTreeMap::new();
        for input_digests in from.iter() {
            let size_before = merged_immutable_inputs.len();
            let immutable_inputs = &input_digests.immutable_inputs;
            merged_immutable_inputs.append(&mut immutable_inputs.clone());
            if size_before + immutable_inputs.len() != merged_immutable_inputs.len() {
                return Err(format!(
            "Tried to merge two-or-more immutable inputs at the same path with different values! \
            The collision involved one of the entries in: {immutable_inputs:?}"
          )
                .into());
            }
        }

        let complete_digests = from
            .iter()
            .map(|input_digests| input_digests.complete.clone())
            .collect();
        let nailgun_digests = from
            .iter()
            .map(|input_digests| input_digests.nailgun.clone())
            .collect();
        let input_files_digests = from
            .iter()
            .map(|input_digests| input_digests.inputs.clone())
            .collect();
        let (complete, nailgun, inputs) = try_join!(
            store.merge(complete_digests),
            store.merge(nailgun_digests),
            store.merge(input_files_digests),
        )?;
        Ok(Self {
            complete,
            nailgun,
            inputs,
            immutable_inputs: merged_immutable_inputs,
            use_nailgun: Itertools::concat(
                from.iter()
                    .map(|input_digests| input_digests.use_nailgun.clone()),
            )
            .into_iter()
            .collect(),
        })
    }

    pub fn with_input_files(inputs: DirectoryDigest) -> Self {
        Self {
            complete: inputs.clone(),
            nailgun: EMPTY_DIRECTORY_DIGEST.clone(),
            inputs,
            immutable_inputs: BTreeMap::new(),
            use_nailgun: BTreeSet::new(),
        }
    }

    /// Split the InputDigests into client and server subsets.
    ///
    /// TODO: The server subset will have an accurate `complete` Digest, but the client will not.
    /// This is currently safe because the nailgun client code does not consume that field, but it
    /// would be good to find a better factoring.
    pub fn nailgun_client_and_server(&self) -> (InputDigests, InputDigests) {
        let (server, client) = self
            .immutable_inputs
            .clone()
            .into_iter()
            .partition(|(path, _digest)| self.use_nailgun.contains(path));

        (
            // Client.
            InputDigests {
                // TODO: See method doc.
                complete: EMPTY_DIRECTORY_DIGEST.clone(),
                nailgun: EMPTY_DIRECTORY_DIGEST.clone(),
                inputs: self.inputs.clone(),
                immutable_inputs: client,
                use_nailgun: BTreeSet::new(),
            },
            // Server.
            InputDigests {
                complete: self.nailgun.clone(),
                nailgun: EMPTY_DIRECTORY_DIGEST.clone(),
                inputs: EMPTY_DIRECTORY_DIGEST.clone(),
                immutable_inputs: server,
                use_nailgun: BTreeSet::new(),
            },
        )
    }
}

impl Default for InputDigests {
    fn default() -> Self {
        Self {
            complete: EMPTY_DIRECTORY_DIGEST.clone(),
            nailgun: EMPTY_DIRECTORY_DIGEST.clone(),
            inputs: EMPTY_DIRECTORY_DIGEST.clone(),
            immutable_inputs: BTreeMap::new(),
            use_nailgun: BTreeSet::new(),
        }
    }
}

#[derive(DeepSizeOf, Debug, Clone, Hash, PartialEq, Eq, Serialize)]
/// "Where" to run a `Process`. This is the Rust-side of the environments feature.
pub enum ProcessExecutionStrategy {
    /// Run the Process locally in an execution sandbox.
    Local,
    /// Run the Process locally in the workspace without an execution sandbox.
    LocalInWorkspace,
    /// Run the Process remotelyt using the Remote Execution API. The vector stores the platform_properties to pass
    /// for that execution.
    RemoteExecution(Vec<(String, String)>),
    /// Run the Process in a Docker container. The string stores the image name.
    Docker(String),
}

impl ProcessExecutionStrategy {
    /// What to insert into the Command proto so that we don't incorrectly cache
    /// Docker vs remote execution vs local execution.
    pub fn cache_value(&self) -> String {
        match self {
            Self::Local => "local_execution".to_string(),
            Self::LocalInWorkspace => "workspace_execution".to_string(),
            Self::RemoteExecution(_) => "remote_execution".to_string(),
            // NB: this image will include the container ID, thanks to
            // https://github.com/pantsbuild/pants/pull/17101.
            Self::Docker(image) => format!("docker_execution: {image}"),
        }
    }

    pub fn strategy_type(&self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::LocalInWorkspace => "workspace",
            Self::RemoteExecution(_) => "remote",
            Self::Docker(_) => "docker",
        }
    }
}

#[derive(DeepSizeOf, Debug, Clone, Hash, PartialEq, Eq, Serialize)]
pub struct ProcessExecutionEnvironment {
    /// The name of the environment the process is running in, or None if it is running in the
    /// default (local) environment.
    pub name: Option<String>,
    pub platform: Platform,
    pub strategy: ProcessExecutionStrategy,
}

///
/// A process to be executed.
///
/// When executing a `Process` using the `local::CommandRunner`, any `{chroot}` placeholders in the
/// environment variables are replaced with the temporary sandbox path.
///
#[derive(DeepSizeOf, Derivative, Clone, Debug, Eq, Serialize)]
#[derivative(PartialEq, Hash)]
pub struct Process {
    ///
    /// The arguments to execute.
    ///
    /// The first argument should be an absolute or relative path to the binary to execute.
    ///
    /// No PATH lookup will be performed unless a PATH environment variable is specified.
    ///
    /// No shell expansion will take place.
    ///
    pub argv: Vec<String>,
    ///
    /// The environment variables to set for the execution.
    ///
    /// No other environment variables will be set (except possibly for an empty PATH variable).
    ///
    pub env: BTreeMap<String, String>,

    ///
    /// A relative path to a directory existing in the `input_files` digest to execute the process
    /// from. Defaults to the `input_files` root.
    ///
    pub working_directory: Option<RelativePath>,

    ///
    /// All of the input digests for the process.
    ///
    pub input_digests: InputDigests,

    pub output_files: BTreeSet<RelativePath>,

    pub output_directories: BTreeSet<RelativePath>,

    pub timeout: Option<std::time::Duration>,

    /// If not None, then a bounded::CommandRunner executing this Process will set an environment
    /// variable with this name containing a unique execution slot number.
    pub execution_slot_variable: Option<String>,

    /// If non-zero, the amount of parallelism that this process is capable of given its inputs. This
    /// value does not directly set the number of cores allocated to the process: that is computed
    /// based on availability, and provided as a template value in the arguments of the process.
    ///
    /// When set, a `{pants_concurrency}` variable will be templated into the `argv` of the process.
    ///
    /// Processes which set this value may be preempted (i.e. canceled and restarted) for a short
    /// period after starting if available resources have changed (because other processes have
    /// started or finished).
    pub concurrency_available: usize,

    #[derivative(PartialEq = "ignore", Hash = "ignore")]
    pub description: String,

    // NB: We serialize with a function to avoid adding a serde dep to the logging crate.
    #[serde(serialize_with = "serialize_level")]
    pub level: log::Level,

    ///
    /// Declares that this process uses the given named caches (which might have associated config
    /// in the future) at the associated relative paths within its workspace. Cache names must
    /// contain only lowercase ascii characters or underscores.
    ///
    /// Caches are exposed to processes within their workspaces at the relative paths represented
    /// by the values of the dict. A process may optionally check for the existence of the relevant
    /// directory, and disable use of that cache if it has not been created by the executor
    /// (indicating a lack of support for this feature).
    ///
    /// These caches are globally shared and so must be concurrency safe: a consumer of the cache
    /// must never assume that it has exclusive access to the provided directory.
    ///
    pub append_only_caches: BTreeMap<CacheName, RelativePath>,

    ///
    /// If present, a symlink will be created at .jdk which points to this directory for local
    /// execution, or a system-installed JDK (ignoring the value of the present Some) for remote
    /// execution.
    ///
    /// This is some technical debt we should clean up;
    /// see <https://github.com/pantsbuild/pants/issues/6416>.
    ///
    pub jdk_home: Option<PathBuf>,

    pub cache_scope: ProcessCacheScope,

    pub execution_environment: ProcessExecutionEnvironment,

    pub remote_cache_speculation_delay: std::time::Duration,

    ///
    /// The attempt number, in the case this Process is being retried.
    ///
    /// This is included in hash/eq so it creates a unique node in the runtime graph.
    ///
    pub attempt: usize,
}

impl Process {
    ///
    /// Constructs a Process with default values for most fields, after which the builder pattern can
    /// be used to set values.
    ///
    /// We use the more ergonomic (but possibly slightly slower) "move self for each builder method"
    /// pattern, so this method should only be used in tests: production usage should construct the
    /// Process struct wholesale. We can reconsider this if we end up with more production callsites
    /// that require partial options.
    ///
    /// NB: Some of the default values used in this constructor only make sense in tests.
    ///
    pub fn new(argv: Vec<String>) -> Process {
        Process {
            argv,
            env: BTreeMap::new(),
            working_directory: None,
            input_digests: InputDigests::default(),
            output_files: BTreeSet::new(),
            output_directories: BTreeSet::new(),
            timeout: None,
            description: "".to_string(),
            level: log::Level::Info,
            append_only_caches: BTreeMap::new(),
            jdk_home: None,
            execution_slot_variable: None,
            concurrency_available: 0,
            cache_scope: ProcessCacheScope::Successful,
            execution_environment: ProcessExecutionEnvironment {
                name: None,
                platform: Platform::current().unwrap(),
                strategy: ProcessExecutionStrategy::Local,
            },
            remote_cache_speculation_delay: std::time::Duration::from_millis(0),
            attempt: 0,
        }
    }

    ///
    /// Replaces the environment for this process.
    ///
    pub fn env(mut self, env: BTreeMap<String, String>) -> Process {
        self.env = env;
        self
    }

    ///
    /// Replaces the working_directory for this process.
    ///
    pub fn working_directory(mut self, working_directory: Option<RelativePath>) -> Process {
        self.working_directory = working_directory;
        self
    }

    ///
    /// Replaces the output files for this process.
    ///
    pub fn output_files(mut self, output_files: BTreeSet<RelativePath>) -> Process {
        self.output_files = output_files;
        self
    }

    ///
    /// Replaces the output directories for this process.
    ///
    pub fn output_directories(mut self, output_directories: BTreeSet<RelativePath>) -> Process {
        self.output_directories = output_directories;
        self
    }

    ///
    /// Replaces the append only caches for this process.
    ///
    pub fn append_only_caches(
        mut self,
        append_only_caches: BTreeMap<CacheName, RelativePath>,
    ) -> Process {
        self.append_only_caches = append_only_caches;
        self
    }

    ///
    /// Set the execution environment to Docker, with the specified image.
    ///
    pub fn docker(mut self, image: String) -> Process {
        self.execution_environment = ProcessExecutionEnvironment {
            name: None,
            platform: Platform::current().unwrap(),
            strategy: ProcessExecutionStrategy::Docker(image),
        };
        self
    }

    ///
    /// Set the execution environment to remote execution with the specified platform properties.
    ///
    pub fn remote_execution(mut self, properties: Vec<(String, String)>) -> Process {
        self.execution_environment = ProcessExecutionEnvironment {
            name: None,
            platform: Platform::current().unwrap(),
            strategy: ProcessExecutionStrategy::RemoteExecution(properties),
        };
        self
    }

    pub fn remote_cache_speculation_delay(mut self, delay: std::time::Duration) -> Process {
        self.remote_cache_speculation_delay = delay;
        self
    }

    pub fn cache_scope(mut self, cache_scope: ProcessCacheScope) -> Process {
        self.cache_scope = cache_scope;
        self
    }
}

///
/// The result of running a process.
///
/// TODO: Rename to `FallibleProcessResult`: see #18450.
///
#[derive(DeepSizeOf, Derivative, Clone, Debug, Eq)]
#[derivative(PartialEq, Hash)]
pub struct FallibleProcessResultWithPlatform {
    pub stdout_digest: Digest,
    pub stderr_digest: Digest,
    pub exit_code: i32,
    pub output_directory: DirectoryDigest,
    #[derivative(PartialEq = "ignore", Hash = "ignore")]
    pub metadata: ProcessResultMetadata,
}

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub struct ProcessResultMetadata {
    /// The execution time of this process when it ran.
    ///
    /// Corresponds to `worker_start_timestamp` and `worker_completed_timestamp` from
    /// `ExecutedActionMetadata`.
    ///
    /// NB: This is optional because the REAPI does not guarantee that it is returned.
    pub total_elapsed: Option<Duration>,
    /// How much faster a cache hit was than running the process again.
    ///
    /// This includes the overhead of setting up and cleaning up the process for execution, and it
    /// should include all overhead for the cache lookup.
    ///
    /// If the cache hit was slower than the original process, we return 0. Note that the cache hit
    /// may still have been faster than rerunning the process a second time, e.g. if speculation
    /// is used and the cache hit completed before the rerun; still, we cannot know how long the
    /// second run would have taken, so the best we can do is report 0.
    ///
    /// If the original process's execution time was not recorded, this may be None.
    pub saved_by_cache: Option<Duration>,
    /// The source of the result.
    pub source: ProcessResultSource,
    /// The environment that the process ran in.
    pub environment: ProcessExecutionEnvironment,
    /// The RunId of the Session in which the `ProcessResultSource` was accurate. In further runs
    /// within the same process, the source of the process implicitly becomes memoization.
    pub source_run_id: RunId,
}

impl ProcessResultMetadata {
    pub fn new(
        total_elapsed: Option<Duration>,
        source: ProcessResultSource,
        environment: ProcessExecutionEnvironment,
        source_run_id: RunId,
    ) -> Self {
        Self {
            total_elapsed,
            saved_by_cache: None,
            source,
            environment,
            source_run_id,
        }
    }

    pub fn new_from_metadata(
        metadata: ExecutedActionMetadata,
        source: ProcessResultSource,
        environment: ProcessExecutionEnvironment,
        source_run_id: RunId,
    ) -> Self {
        let total_elapsed = match (
            metadata.worker_start_timestamp,
            metadata.worker_completed_timestamp,
        ) {
            (Some(started), Some(completed)) => {
                TimeSpan::from_start_and_end(&started, &completed, "")
                    .map(|span| span.duration)
                    .ok()
            }
            _ => None,
        };

        Self::new(total_elapsed, source, environment, source_run_id)
    }

    pub fn update_cache_hit_elapsed(&mut self, cache_hit_elapsed: std::time::Duration) {
        self.saved_by_cache = self.total_elapsed.map(|total_elapsed| {
            let total_elapsed: std::time::Duration = total_elapsed.into();
            total_elapsed
                .checked_sub(cache_hit_elapsed)
                .unwrap_or_else(|| std::time::Duration::new(0, 0))
                .into()
        });
    }
}

impl From<ProcessResultMetadata> for ExecutedActionMetadata {
    fn from(metadata: ProcessResultMetadata) -> ExecutedActionMetadata {
        let (total_start, total_end) = match metadata.total_elapsed {
            Some(elapsed) => {
                // Because we do not have the precise start time, we hardcode to starting at UNIX_EPOCH. We
                // only care about accurately preserving the duration.
                let start = prost_types::Timestamp {
                    seconds: 0,
                    nanos: 0,
                };
                let end = prost_types::Timestamp {
                    seconds: elapsed.secs as i64,
                    nanos: elapsed.nanos as i32,
                };
                (Some(start), Some(end))
            }
            None => (None, None),
        };
        ExecutedActionMetadata {
            worker_start_timestamp: total_start,
            worker_completed_timestamp: total_end,
            ..ExecutedActionMetadata::default()
        }
    }
}

#[derive(Clone, Copy, Debug, DeepSizeOf, Eq, PartialEq)]
pub enum ProcessResultSource {
    Ran,
    HitLocally,
    HitRemotely,
}

impl From<ProcessResultSource> for &'static str {
    fn from(prs: ProcessResultSource) -> &'static str {
        match prs {
            ProcessResultSource::Ran => "ran",
            ProcessResultSource::HitLocally => "hit_locally",
            ProcessResultSource::HitRemotely => "hit_remotely",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, strum_macros::EnumString)]
#[strum(serialize_all = "snake_case")]
pub enum CacheContentBehavior {
    Fetch,
    Validate,
    Defer,
}

///
/// Optionally validate that all digests in the result are loadable, returning false if any are not.
///
/// If content loading is deferred, a Digest which is discovered to be missing later on during
/// execution will cause backtracking.
///
pub async fn check_cache_content(
    response: &FallibleProcessResultWithPlatform,
    store: &Store,
    cache_content_behavior: CacheContentBehavior,
) -> Result<bool, StoreError> {
    match cache_content_behavior {
        CacheContentBehavior::Fetch => {
            let response = response.clone();
            let fetch_result =
                in_workunit!("eager_fetch_action_cache", Level::Trace, |_workunit| store
                    .ensure_downloaded(
                        HashSet::from([response.stdout_digest, response.stderr_digest]),
                        HashSet::from([response.output_directory])
                    ))
                .await;
            match fetch_result {
                Err(StoreError::MissingDigest { .. }) => Ok(false),
                Ok(_) => Ok(true),
                Err(e) => Err(e),
            }
        }
        CacheContentBehavior::Validate => {
            let directory_digests = vec![response.output_directory.clone()];
            let file_digests = vec![response.stdout_digest, response.stderr_digest];
            in_workunit!(
                "eager_validate_action_cache",
                Level::Trace,
                |_workunit| async move {
                    store
                        .exists_recursive(directory_digests, file_digests)
                        .await
                }
            )
            .await
        }
        CacheContentBehavior::Defer => Ok(true),
    }
}

#[derive(Clone)]
pub struct Context {
    pub workunit_store: WorkunitStore,
    pub build_id: String,
    pub run_id: RunId,
    pub tail_tasks: TailTasks,
}

impl Default for Context {
    fn default() -> Self {
        Context {
            workunit_store: WorkunitStore::new(false, log::Level::Debug),
            build_id: String::default(),
            run_id: RunId(0),
            tail_tasks: TailTasks::new(),
        }
    }
}

impl Context {
    pub fn new(
        workunit_store: WorkunitStore,
        build_id: String,
        run_id: RunId,
        tail_tasks: TailTasks,
    ) -> Context {
        Context {
            workunit_store,
            build_id,
            run_id,
            tail_tasks,
        }
    }
}

#[async_trait]
pub trait CommandRunner: Send + Sync + Debug {
    ///
    /// Submit a request for execution on the underlying runtime, and return
    /// a future for it.
    ///
    async fn run(
        &self,
        context: Context,
        workunit: &mut RunningWorkunit,
        req: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError>;

    /// Shutdown this CommandRunner cleanly.
    async fn shutdown(&self) -> Result<(), String>;
}

#[async_trait]
impl<T: CommandRunner + ?Sized> CommandRunner for Box<T> {
    async fn run(
        &self,
        context: Context,
        workunit: &mut RunningWorkunit,
        req: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
        (**self).run(context, workunit, req).await
    }

    async fn shutdown(&self) -> Result<(), String> {
        (**self).shutdown().await
    }
}

#[async_trait]
impl<T: CommandRunner + ?Sized> CommandRunner for Arc<T> {
    async fn run(
        &self,
        context: Context,
        workunit: &mut RunningWorkunit,
        req: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
        (**self).run(context, workunit, req).await
    }

    async fn shutdown(&self) -> Result<(), String> {
        (**self).shutdown().await
    }
}

// TODO(#8513) possibly move to the MEPR struct, or to the hashing crate?
pub async fn get_digest(
    process: &Process,
    instance_name: Option<String>,
    process_cache_namespace: Option<String>,
    store: &Store,
    append_only_caches_base_path: Option<&str>,
) -> Digest {
    let EntireExecuteRequest {
        execute_request, ..
    } = make_execute_request(
        process,
        instance_name,
        process_cache_namespace,
        store,
        append_only_caches_base_path,
    )
    .await
    .unwrap();
    execute_request.action_digest.unwrap().try_into().unwrap()
}

pub fn digest<T: prost::Message>(message: &T) -> Result<Digest, String> {
    Ok(Digest::of_bytes(&message.to_bytes()))
}

#[derive(Clone, Debug, PartialEq)]
pub struct EntireExecuteRequest {
    pub action: Action,
    pub command: Command,
    pub execute_request: ExecuteRequest,
    pub input_root_digest: DirectoryDigest,
}

fn make_wrapper_for_append_only_caches(
    caches: &BTreeMap<CacheName, RelativePath>,
    base_path: &str,
    working_directory: Option<&str>,
) -> Result<String, String> {
    let mut script = String::new();
    writeln!(&mut script, "#!/bin/sh").map_err(|err| format!("write! failed: {err:?}"))?;

    // Setup the append-only caches.
    for (cache_name, path) in caches {
        writeln!(
            &mut script,
            "/bin/mkdir -p '{}/{}'",
            base_path,
            cache_name.name()
        )
        .map_err(|err| format!("write! failed: {err:?}"))?;
        if let Some(parent) = path.parent() {
            writeln!(&mut script, "/bin/mkdir -p '{}'", parent.to_string_lossy())
                .map_err(|err| format!("write! failed: {err}"))?;
        }
        writeln!(
            &mut script,
            "/bin/ln -s '{}/{}' '{}'",
            base_path,
            cache_name.name(),
            path.as_path().to_string_lossy()
        )
        .map_err(|err| format!("write! failed: {err}"))?;
    }

    // Change into any working directory.
    //
    // Note: When this wrapper script is in effect, Pants will not set the `working_directory`
    // field on the `ExecuteRequest` so that this wrapper script can operate in the input root
    // first.
    if let Some(path) = working_directory {
        writeln!(
            &mut script,
            concat!(
                "cd '{0}'\n",
                "if [ \"$?\" != 0 ]; then\n",
                "  echo \"pants-wrapper: Failed to change working directory to: {0}\" 1>&2\n",
                "  exit 1\n",
                "fi\n",
            ),
            path
        )
        .map_err(|err| format!("write! failed: {err}"))?;
    }

    // Finally, execute the process.
    writeln!(&mut script, "exec \"$@\"").map_err(|err| format!("write! failed: {err:?}"))?;
    Ok(script)
}

pub async fn make_execute_request(
    req: &Process,
    instance_name: Option<String>,
    cache_key_gen_version: Option<String>,
    store: &Store,
    append_only_caches_base_path: Option<&str>,
) -> Result<EntireExecuteRequest, String> {
    const WRAPPER_SCRIPT: &str = "./__pants_wrapper__";

    // Implement append-only caches by running a wrapper script before the actual program
    // to be invoked in the remote environment.
    let wrapper_script_digest_opt = match (append_only_caches_base_path, &req.append_only_caches) {
        (Some(base_path), caches) if !caches.is_empty() => {
            let script = make_wrapper_for_append_only_caches(
                caches,
                base_path,
                req.working_directory.as_ref().and_then(|p| p.to_str()),
            )?;
            let digest = store
                .store_file_bytes(Bytes::from(script), false)
                .await
                .map_err(|err| {
                    format!("Failed to store wrapper script for remote execution: {err}")
                })?;
            let path = RelativePath::new(Path::new(WRAPPER_SCRIPT))?;
            let snapshot = store.snapshot_of_one_file(path, digest, true).await?;
            let directory_digest = DirectoryDigest::new(snapshot.digest, snapshot.tree);
            Some(directory_digest)
        }
        _ => None,
    };

    let arguments = match &wrapper_script_digest_opt {
        Some(_) => {
            let mut args = Vec::with_capacity(req.argv.len() + 1);
            args.push(WRAPPER_SCRIPT.to_string());
            args.extend(req.argv.iter().cloned());
            args
        }
        None => req.argv.clone(),
    };

    let mut command = remexec::Command {
        arguments,
        ..remexec::Command::default()
    };

    for (name, value) in &req.env {
        if name == CACHE_KEY_GEN_VERSION_ENV_VAR_NAME
            || name == CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME
            || name == CACHE_KEY_SALT_ENV_VAR_NAME
        {
            return Err(format!(
                "Cannot set env var with name {name} as that is reserved for internal use by pants"
            ));
        }

        command
            .environment_variables
            .push(remexec::command::EnvironmentVariable {
                name: name.to_string(),
                value: value.to_string(),
            });
    }

    let mut platform_properties = match &req.execution_environment.strategy {
        ProcessExecutionStrategy::RemoteExecution(properties) => properties.clone(),
        _ => vec![],
    };

    if let Some(cache_key_gen_version) = cache_key_gen_version {
        command
            .environment_variables
            .push(remexec::command::EnvironmentVariable {
                name: CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_string(),
                value: cache_key_gen_version,
            });
    }

    command
        .environment_variables
        .push(remexec::command::EnvironmentVariable {
            name: CACHE_KEY_EXECUTION_STRATEGY.to_string(),
            value: req.execution_environment.strategy.cache_value(),
        });

    if matches!(
        req.cache_scope,
        ProcessCacheScope::PerSession
            | ProcessCacheScope::PerRestartAlways
            | ProcessCacheScope::PerRestartSuccessful
    ) {
        command
            .environment_variables
            .push(remexec::command::EnvironmentVariable {
                name: CACHE_KEY_SALT_ENV_VAR_NAME.to_string(),
                value: Uuid::new_v4().to_string(),
            });
    }

    {
        command
            .environment_variables
            .push(remexec::command::EnvironmentVariable {
                name: CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_string(),
                value: req.execution_environment.platform.into(),
            });
    }

    let mut output_files = req
        .output_files
        .iter()
        .map(|p| {
            p.to_str()
                .map(str::to_owned)
                .ok_or_else(|| format!("Non-UTF8 output file path: {p:?}"))
        })
        .collect::<Result<Vec<String>, String>>()?;
    output_files.sort();
    command.output_files = output_files;

    let mut output_directories = req
        .output_directories
        .iter()
        .map(|p| {
            p.to_str()
                .map(str::to_owned)
                .ok_or_else(|| format!("Non-UTF8 output directory path: {p:?}"))
        })
        .collect::<Result<Vec<String>, String>>()?;
    output_directories.sort();
    command.output_directories = output_directories;

    if let Some(working_directory) = &req.working_directory {
        // Do not set `working_directory` if a wrapper script is in use because the wrapper script
        // will change to the working directory itself.
        if wrapper_script_digest_opt.is_none() {
            command.working_directory = working_directory
                .to_str()
                .map(str::to_owned)
                .unwrap_or_else(|| {
                    panic!("Non-UTF8 working directory path: {working_directory:?}")
                });
        }
    }

    if req.jdk_home.is_some() {
        // Ideally, the JDK would be brought along as part of the input directory, but we don't
        // currently have support for that. Scoot supports this property, and will symlink .jdk to a
        // system-installed JDK https://github.com/twitter/scoot/pull/391 - we should probably come to
        // some kind of consensus across tools as to how this should work; RBE appears to work by
        // allowing you to specify a jdk-version platform property, and it will put a JDK at a
        // well-known path in the docker container you specify in which to run.
        platform_properties.push(("JDK_SYMLINK".to_owned(), ".jdk".to_owned()));
    }

    // Extract `Platform` proto from the `Command` to avoid a partial move of `Command`.
    let mut command_platform = command.platform.take().unwrap_or_default();

    // Add configured platform properties to the `Platform`.
    for (name, value) in platform_properties {
        command_platform
            .properties
            .push(remexec::platform::Property {
                name: name.clone(),
                value: value.clone(),
            });
    }

    // Sort the platform properties.
    //
    // From the remote execution spec:
    //   The properties that make up this platform. In order to ensure that
    //   equivalent `Platform`s always hash to the same value, the properties MUST
    //   be lexicographically sorted by name, and then by value. Sorting of strings
    //   is done by code point, equivalently, by the UTF-8 bytes.
    //
    // Note: BuildBarn enforces this requirement.
    command_platform
        .properties
        .sort_by(|x, y| match x.name.cmp(&y.name) {
            Ordering::Equal => x.value.cmp(&y.value),
            v => v,
        });

    // Store the separate copy back into the Command proto.
    command.platform = Some(command_platform);

    // Sort the environment variables. REv2 spec requires sorting by name for same reasons that
    // platform properties are sorted, i.e. consistent hashing.
    command
        .environment_variables
        .sort_by(|x, y| x.name.cmp(&y.name));

    let input_root_digest: DirectoryDigest = match &wrapper_script_digest_opt {
        Some(wrapper_digest) => {
            let digests = vec![
                req.input_digests.complete.clone(),
                wrapper_digest.to_owned(),
            ];
            store
                .merge(digests)
                .await
                .map_err(|err| format!("store error: {err}"))?
        }
        None => req.input_digests.complete.clone(),
    };

    let mut action = remexec::Action {
        command_digest: Some((&digest(&command)?).into()),
        input_root_digest: Some(input_root_digest.as_digest().into()),
        ..remexec::Action::default()
    };

    if let Some(timeout) = req.timeout {
        action.timeout = Some(prost_types::Duration::try_from(timeout).unwrap());
    }

    let execute_request = remexec::ExecuteRequest {
        action_digest: Some((&digest(&action)?).into()),
        instance_name: instance_name.unwrap_or_else(|| "".to_owned()),
        // We rely on the RemoteCache command runner for caching with remote execution. We always
        // disable remote servers from doing caching themselves not only to avoid wasted work, but
        // more importantly because they do not have our same caching semantics, e.g.
        // `ProcessCacheScope.SUCCESSFUL` vs `ProcessCacheScope.ALWAYS`.
        skip_cache_lookup: true,
        ..remexec::ExecuteRequest::default()
    };

    Ok(EntireExecuteRequest {
        action,
        command,
        execute_request,
        input_root_digest,
    })
}

/// Convert an ActionResult into a FallibleProcessResultWithPlatform.
///
/// HACK: The caching CommandRunner stores the digest of the Directory that merges all output
/// files and output directories in the `tree_digest` field of the `output_directories` field
/// of the ActionResult/ExecuteResponse stored in the local cache. When
/// `treat_tree_digest_as_final_directory_hack` is true, then that final merged directory
/// will be extracted from the tree_digest of the single output directory.
pub async fn populate_fallible_execution_result(
    store: Store,
    run_id: RunId,
    action_result: &remexec::ActionResult,
    treat_tree_digest_as_final_directory_hack: bool,
    source: ProcessResultSource,
    environment: ProcessExecutionEnvironment,
) -> Result<FallibleProcessResultWithPlatform, StoreError> {
    let (stdout_digest, stderr_digest, output_directory) = future::try_join3(
        extract_stdout(&store, action_result),
        extract_stderr(&store, action_result),
        extract_output_files(
            store,
            action_result,
            treat_tree_digest_as_final_directory_hack,
        ),
    )
    .await?;

    let metadata = if let Some(metadata) = action_result.execution_metadata.clone() {
        ProcessResultMetadata::new_from_metadata(metadata, source, environment, run_id)
    } else {
        ProcessResultMetadata::new(None, source, environment, run_id)
    };

    Ok(FallibleProcessResultWithPlatform {
        stdout_digest,
        stderr_digest,
        exit_code: action_result.exit_code,
        output_directory,
        metadata,
    })
}

fn extract_stdout<'a>(
    store: &Store,
    action_result: &'a remexec::ActionResult,
) -> BoxFuture<'a, Result<Digest, StoreError>> {
    let store = store.clone();
    async move {
        if let Some(digest_proto) = &action_result.stdout_digest {
            let stdout_digest_result: Result<Digest, String> = digest_proto.try_into();
            let stdout_digest =
                stdout_digest_result.map_err(|err| format!("Error extracting stdout: {err}"))?;
            Ok(stdout_digest)
        } else {
            let stdout_raw = Bytes::copy_from_slice(&action_result.stdout_raw);
            let digest = store
                .store_file_bytes(stdout_raw, true)
                .map_err(move |error| format!("Error storing raw stdout: {error:?}"))
                .await?;
            Ok(digest)
        }
    }
    .boxed()
}

fn extract_stderr<'a>(
    store: &Store,
    action_result: &'a remexec::ActionResult,
) -> BoxFuture<'a, Result<Digest, StoreError>> {
    let store = store.clone();
    async move {
        if let Some(digest_proto) = &action_result.stderr_digest {
            let stderr_digest_result: Result<Digest, String> = digest_proto.try_into();
            let stderr_digest =
                stderr_digest_result.map_err(|err| format!("Error extracting stderr: {err}"))?;
            Ok(stderr_digest)
        } else {
            let stderr_raw = Bytes::copy_from_slice(&action_result.stderr_raw);
            let digest = store
                .store_file_bytes(stderr_raw, true)
                .map_err(move |error| format!("Error storing raw stderr: {error:?}"))
                .await?;
            Ok(digest)
        }
    }
    .boxed()
}

pub fn extract_output_files(
    store: Store,
    action_result: &remexec::ActionResult,
    treat_tree_digest_as_final_directory_hack: bool,
) -> BoxFuture<'static, Result<DirectoryDigest, StoreError>> {
    // HACK: The caching CommandRunner stores the digest of the Directory that merges all output
    // files and output directories in the `tree_digest` field of the `output_directories` field
    // of the ActionResult/ExecuteResponse stored in the local cache. When
    // `treat_tree_digest_as_final_directory_hack` is true, then this code will extract that
    // directory from the tree_digest and skip the merging performed by the remainder of this
    // method.
    if treat_tree_digest_as_final_directory_hack {
        match &action_result.output_directories[..] {
            [directory] => {
                match require_digest(directory.tree_digest.as_ref()) {
                    Ok(digest) => {
                        return future::ready::<Result<_, StoreError>>(Ok(
                            DirectoryDigest::from_persisted_digest(digest),
                        ))
                        .boxed()
                    }
                    Err(err) => return futures::future::err(err.into()).boxed(),
                };
            }
            _ => {
                return futures::future::err(
                    "illegal state: treat_tree_digest_as_final_directory_hack \
          expected single output directory"
                        .to_owned()
                        .into(),
                )
                .boxed();
            }
        }
    }

    // Get Digests of output Directories.
    // Then we'll make a Directory for the output files, and merge them.
    let mut directory_digests = Vec::with_capacity(action_result.output_directories.len() + 1);
    // TODO: Maybe take rather than clone
    let output_directories = action_result.output_directories.clone();
    for dir in output_directories {
        let store = store.clone();
        directory_digests.push(
            (async move {
                // The `OutputDirectory` contains the digest of a `Tree` proto which contains
                // the `Directory` proto of the root directory of this `OutputDirectory` plus all
                // of the `Directory` protos for child directories of that root.

                // Retrieve the Tree proto and hash its root `Directory` proto to obtain the digest
                // of the output directory needed to construct the series of `Directory` protos needed
                // for the final merge of the output directories.
                let tree_digest: Digest = require_digest(dir.tree_digest.as_ref())?;
                let directory_digest = store
                    .load_tree_from_remote(tree_digest)
                    .await?
                    .ok_or_else(|| format!("Tree with digest {tree_digest:?} was not in remote"))?;

                store
                    .add_prefix(directory_digest, &RelativePath::new(dir.path)?)
                    .await
            })
            .map_err(|err| format!("Error saving remote output directory to local cache: {err}")),
        );
    }

    // Make a directory for the files
    let mut path_map = HashMap::new();
    let path_stats_result: Result<Vec<PathStat>, String> = action_result
        .output_files
        .iter()
        .map(|output_file| {
            let output_file_path_buf = PathBuf::from(output_file.path.clone());
            let digest: Result<Digest, String> = require_digest(output_file.digest.as_ref());
            path_map.insert(output_file_path_buf.clone(), digest?);
            Ok(PathStat::file(
                output_file_path_buf.clone(),
                File {
                    path: output_file_path_buf,
                    is_executable: output_file.is_executable,
                },
            ))
        })
        .collect();

    let path_stats = try_future!(path_stats_result);

    #[derive(Clone)]
    struct StoreOneOffRemoteDigest {
        map_of_paths_to_digests: HashMap<PathBuf, Digest>,
    }

    impl StoreOneOffRemoteDigest {
        fn new(map: HashMap<PathBuf, Digest>) -> StoreOneOffRemoteDigest {
            StoreOneOffRemoteDigest {
                map_of_paths_to_digests: map,
            }
        }
    }

    impl StoreFileByDigest<String> for StoreOneOffRemoteDigest {
        fn store_by_digest(
            &self,
            file: File,
        ) -> future::BoxFuture<'static, Result<Digest, String>> {
            match self.map_of_paths_to_digests.get(&file.path) {
                Some(digest) => future::ok(*digest),
                None => future::err(format!(
                    "Didn't know digest for path in remote execution response: {:?}",
                    file.path
                )),
            }
            .boxed()
        }
    }

    async move {
        let files_snapshot =
            Snapshot::from_path_stats(StoreOneOffRemoteDigest::new(path_map), path_stats).map_err(
                move |error| {
                    format!(
                "Error when storing the output file directory info in the remote CAS: {error:?}"
            )
                },
            );

        let (files_snapshot, mut directory_digests) =
            future::try_join(files_snapshot, future::try_join_all(directory_digests)).await?;

        directory_digests.push(files_snapshot.into());

        store
            .merge(directory_digests)
            .map_err(|err| err.enrich("Error when merging output files and directories"))
            .await
    }
    .boxed()
}

#[cfg(test)]
mod tests;
