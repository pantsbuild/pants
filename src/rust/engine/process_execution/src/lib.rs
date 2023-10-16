// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
    clippy::unseparated_literal_suffix,
    clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
    clippy::len_without_is_empty,
    clippy::redundant_field_names,
    clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]
#[macro_use]
extern crate derivative;

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::convert::{TryFrom, TryInto};
use std::fmt::{self, Debug, Display};
use std::path::PathBuf;
use std::sync::Arc;

use async_trait::async_trait;
use concrete_time::{Duration, TimeSpan};
use deepsize::DeepSizeOf;
use fs::{DirectoryDigest, RelativePath, EMPTY_DIRECTORY_DIGEST};
use futures::future::try_join_all;
use futures::try_join;
use hashing::Digest;
use itertools::Itertools;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::ExecutedActionMetadata;
use serde::{Deserialize, Serialize};
use store::{SnapshotOps, Store, StoreError};
use task_executor::TailTasks;
use workunit_store::{in_workunit, Level, RunId, RunningWorkunit, WorkunitStore};

pub mod bounded;
#[cfg(test)]
mod bounded_tests;

pub mod cache;
#[cfg(test)]
mod cache_tests;

pub mod switched;

pub mod children;

pub mod docker;
#[cfg(test)]
mod docker_tests;

pub mod immutable_inputs;

pub mod local;
#[cfg(test)]
mod local_tests;

pub mod nailgun;

pub mod named_caches;

pub mod remote;
#[cfg(test)]
pub mod remote_tests;

pub mod remote_cache;
#[cfg(test)]
mod remote_cache_tests;

extern crate uname;

pub use crate::children::ManagedChild;
pub use crate::immutable_inputs::ImmutableInputs;
pub use crate::named_caches::{CacheName, NamedCaches};
pub use crate::remote_cache::RemoteCacheWarningsBehavior;

use crate::remote::EntireExecuteRequest;

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
                "Found unknown system/arch name pair {} {}",
                sysname, machine
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
            other => Err(format!(
                "Unknown platform {:?} encountered in parsing",
                other
            )),
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
            other => Err(format!("Unknown Process cache scope: {:?}", other)),
        }
    }
}

fn serialize_level<S: serde::Serializer>(level: &log::Level, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&level.to_string())
}

/// A symlink from a relative src to an absolute dst (outside of the workdir).
#[derive(Debug)]
pub struct WorkdirSymlink {
    pub src: RelativePath,
    pub dst: PathBuf,
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
    /// TODO: Rename to `inputs` for symmetry with `immutable_inputs`.
    pub input_files: DirectoryDigest,

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
        input_files: DirectoryDigest,
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
        complete_digests.push(input_files.clone());

        let (complete, nailgun) =
            try_join!(store.merge(complete_digests), store.merge(nailgun_digests),)?;
        Ok(Self {
            complete: complete,
            nailgun: nailgun,
            input_files,
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
            .map(|input_digests| input_digests.input_files.clone())
            .collect();
        let (complete, nailgun, input_files) = try_join!(
            store.merge(complete_digests),
            store.merge(nailgun_digests),
            store.merge(input_files_digests),
        )?;
        Ok(Self {
            complete: complete,
            nailgun: nailgun,
            input_files: input_files,
            immutable_inputs: merged_immutable_inputs,
            use_nailgun: Itertools::concat(
                from.iter()
                    .map(|input_digests| input_digests.use_nailgun.clone()),
            )
            .into_iter()
            .collect(),
        })
    }

    pub fn with_input_files(input_files: DirectoryDigest) -> Self {
        Self {
            complete: input_files.clone(),
            nailgun: EMPTY_DIRECTORY_DIGEST.clone(),
            input_files,
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
                input_files: self.input_files.clone(),
                immutable_inputs: client,
                use_nailgun: BTreeSet::new(),
            },
            // Server.
            InputDigests {
                complete: self.nailgun.clone(),
                nailgun: EMPTY_DIRECTORY_DIGEST.clone(),
                input_files: EMPTY_DIRECTORY_DIGEST.clone(),
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
            input_files: EMPTY_DIRECTORY_DIGEST.clone(),
            immutable_inputs: BTreeMap::new(),
            use_nailgun: BTreeSet::new(),
        }
    }
}

#[derive(DeepSizeOf, Debug, Clone, Hash, PartialEq, Eq, Serialize)]
pub enum ProcessExecutionStrategy {
    Local,
    /// Stores the platform_properties.
    RemoteExecution(Vec<(String, String)>),
    /// Stores the image name.
    Docker(String),
}

impl ProcessExecutionStrategy {
    /// What to insert into the Command proto so that we don't incorrectly cache
    /// Docker vs remote execution vs local execution.
    pub fn cache_value(&self) -> String {
        match self {
            Self::Local => "local_execution".to_string(),
            Self::RemoteExecution(_) => "remote_execution".to_string(),
            // NB: this image will include the container ID, thanks to
            // https://github.com/pantsbuild/pants/pull/17101.
            Self::Docker(image) => format!("docker_execution: {image}"),
        }
    }
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
    /// see https://github.com/pantsbuild/pants/issues/6416.
    ///
    pub jdk_home: Option<PathBuf>,

    pub platform: Platform,

    pub cache_scope: ProcessCacheScope,

    pub execution_strategy: ProcessExecutionStrategy,

    pub remote_cache_speculation_delay: std::time::Duration,
}

impl Process {
    ///
    /// Constructs a Process with default values for most fields, after which the builder pattern can
    /// be used to set values.
    ///
    /// We use the more ergonomic (but possibly slightly slower) "move self for each builder method"
    /// pattern, so this method is only enabled for test usage: production usage should construct the
    /// Process struct wholesale. We can reconsider this if we end up with more production callsites
    /// that require partial options.
    ///
    #[cfg(test)]
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
            platform: Platform::current().unwrap(),
            execution_slot_variable: None,
            concurrency_available: 0,
            cache_scope: ProcessCacheScope::Successful,
            execution_strategy: ProcessExecutionStrategy::Local,
            remote_cache_speculation_delay: std::time::Duration::from_millis(0),
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
    /// Set the execution strategy to Docker, with the specified image.
    ///
    pub fn docker(mut self, image: String) -> Process {
        self.execution_strategy = ProcessExecutionStrategy::Docker(image);
        self
    }

    ///
    /// Set the execution strategy to remote execution with the provided platform properties.
    ///
    pub fn remote_execution_platform_properties(
        mut self,
        properties: Vec<(String, String)>,
    ) -> Process {
        self.execution_strategy = ProcessExecutionStrategy::RemoteExecution(properties);
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
#[derive(DeepSizeOf, Derivative, Clone, Debug, Eq)]
#[derivative(PartialEq, Hash)]
pub struct FallibleProcessResultWithPlatform {
    pub stdout_digest: Digest,
    pub stderr_digest: Digest,
    pub exit_code: i32,
    pub output_directory: DirectoryDigest,
    pub platform: Platform,
    #[derivative(PartialEq = "ignore", Hash = "ignore")]
    pub metadata: ProcessResultMetadata,
}

/// Metadata for a ProcessResult corresponding to the REAPI `ExecutedActionMetadata` proto. This
/// conversion is lossy, but the interesting parts are preserved.
#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub struct ProcessResultMetadata {
    /// The time from starting to completion, including preparing the chroot and cleanup.
    /// Corresponds to `worker_start_timestamp` and `worker_completed_timestamp` from
    /// `ExecutedActionMetadata`.
    ///
    /// NB: This is optional because the REAPI does not guarantee that it is returned.
    pub total_elapsed: Option<Duration>,
    /// The source of the result.
    pub source: ProcessResultSource,
    /// The RunId of the Session in which the `ProcessResultSource` was accurate. In further runs
    /// within the same process, the source of the process implicitly becomes memoization.
    pub source_run_id: RunId,
}

impl ProcessResultMetadata {
    pub fn new(
        total_elapsed: Option<Duration>,
        source: ProcessResultSource,
        source_run_id: RunId,
    ) -> Self {
        Self {
            total_elapsed,
            source,
            source_run_id,
        }
    }

    pub fn new_from_metadata(
        metadata: ExecutedActionMetadata,
        source: ProcessResultSource,
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
        Self {
            total_elapsed,
            source,
            source_run_id,
        }
    }

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
    /// If the original process's execution time was not recorded, we return None because we
    /// cannot make a meaningful comparison.
    pub fn time_saved_from_cache(
        &self,
        cache_lookup: std::time::Duration,
    ) -> Option<std::time::Duration> {
        self.total_elapsed.and_then(|original_process| {
            let original_process: std::time::Duration = original_process.into();
            original_process
                .checked_sub(cache_lookup)
                .or_else(|| Some(std::time::Duration::new(0, 0)))
        })
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
    RanLocally,
    RanRemotely,
    HitLocally,
    HitRemotely,
}

impl From<ProcessResultSource> for &'static str {
    fn from(prs: ProcessResultSource) -> &'static str {
        match prs {
            ProcessResultSource::RanLocally => "ran_locally",
            ProcessResultSource::RanRemotely => "ran_remotely",
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
pub(crate) async fn check_cache_content(
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
    workunit_store: WorkunitStore,
    build_id: String,
    run_id: RunId,
    tail_tasks: TailTasks,
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
pub async fn digest(
    process: &Process,
    instance_name: Option<String>,
    process_cache_namespace: Option<String>,
    store: &Store,
    append_only_caches_base_path: Option<&str>,
) -> Digest {
    let EntireExecuteRequest {
        execute_request, ..
    } = remote::make_execute_request(
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

#[cfg(test)]
mod tests;
