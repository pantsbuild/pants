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

use std::collections::{BTreeMap, BTreeSet};
use std::convert::{TryFrom, TryInto};
use std::path::PathBuf;

use async_trait::async_trait;
use concrete_time::{Duration, TimeSpan};
use deepsize::DeepSizeOf;
use fs::{DirectoryDigest, RelativePath};
use futures::future::try_join_all;
use futures::try_join;
use hashing::Digest;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::ExecutedActionMetadata;
use serde::{Deserialize, Serialize};
use store::{SnapshotOps, SnapshotOpsError, Store};
use workunit_store::{RunId, RunningWorkunit, WorkunitStore};

pub mod bounded;
#[cfg(test)]
mod bounded_tests;

pub mod cache;
#[cfg(test)]
mod cache_tests;

pub mod children;

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

#[derive(
  PartialOrd, Ord, Clone, Copy, Debug, DeepSizeOf, Eq, PartialEq, Hash, Serialize, Deserialize,
)]
#[allow(non_camel_case_types)]
pub enum Platform {
  Macos_x86_64,
  Macos_arm64,
  Linux_x86_64,
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
  pub complete: Digest,

  /// The merged Digest of any `use_nailgun`-relevant Digests.
  pub nailgun: Digest,

  /// The input files for the process execution, which will be materialized as mutable inputs in a
  /// sandbox for the process.
  ///
  /// TODO: Rename to `inputs` for symmetry with `immutable_inputs`.
  pub input_files: Digest,

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
  pub immutable_inputs: BTreeMap<RelativePath, Digest>,

  /// If non-empty, use nailgun in supported runners, using the specified `immutable_inputs` keys
  /// as server inputs. All other keys (and the input_files) will be client inputs.
  pub use_nailgun: Vec<RelativePath>,
}

impl InputDigests {
  pub async fn new(
    store: &Store,
    input_files: Digest,
    immutable_inputs: BTreeMap<RelativePath, Digest>,
    use_nailgun: Vec<RelativePath>,
  ) -> Result<Self, SnapshotOpsError> {
    // Collect all digests into `complete`.
    let mut complete_digests = try_join_all(
      immutable_inputs
        .iter()
        .map(|(path, digest)| store.add_prefix(DirectoryDigest::todo_from_digest(*digest), path))
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
    complete_digests.push(DirectoryDigest::todo_from_digest(input_files));

    let (complete, nailgun) =
      try_join!(store.merge(complete_digests), store.merge(nailgun_digests),)?;
    Ok(Self {
      complete: complete.todo_as_digest(),
      nailgun: nailgun.todo_as_digest(),
      input_files,
      immutable_inputs,
      use_nailgun,
    })
  }

  pub fn with_input_files(input_files: Digest) -> Self {
    Self {
      complete: input_files,
      nailgun: hashing::EMPTY_DIGEST,
      input_files,
      immutable_inputs: BTreeMap::new(),
      use_nailgun: Vec::new(),
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
        complete: hashing::EMPTY_DIGEST,
        nailgun: hashing::EMPTY_DIGEST,
        input_files: self.input_files,
        immutable_inputs: client,
        use_nailgun: vec![],
      },
      // Server.
      InputDigests {
        complete: self.nailgun,
        nailgun: hashing::EMPTY_DIGEST,
        input_files: hashing::EMPTY_DIGEST,
        immutable_inputs: server,
        use_nailgun: vec![],
      },
    )
  }
}

impl Default for InputDigests {
  fn default() -> Self {
    Self {
      complete: hashing::EMPTY_DIGEST,
      nailgun: hashing::EMPTY_DIGEST,
      input_files: hashing::EMPTY_DIGEST,
      immutable_inputs: BTreeMap::new(),
      use_nailgun: Vec::new(),
    }
  }
}

///
/// A process to be executed.
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

  pub platform_constraint: Option<Platform>,

  pub cache_scope: ProcessCacheScope,
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
      platform_constraint: None,
      execution_slot_variable: None,
      concurrency_available: 0,
      cache_scope: ProcessCacheScope::Successful,
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
}

///
/// Metadata surrounding an Process which factors into its cache key when cached
/// externally from the engine graph (e.g. when using remote execution or an external process
/// cache).
///
#[derive(Clone, Debug, Default)]
pub struct ProcessMetadata {
  pub instance_name: Option<String>,
  pub cache_key_gen_version: Option<String>,
  pub platform_properties: Vec<(String, String)>,
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
  pub output_directory: hashing::Digest,
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
      (Some(started), Some(completed)) => TimeSpan::from_start_and_end(&started, &completed, "")
        .map(|span| span.duration)
        .ok(),
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

#[derive(Clone)]
pub struct Context {
  workunit_store: WorkunitStore,
  build_id: String,
  run_id: RunId,
}

impl Default for Context {
  fn default() -> Self {
    Context {
      workunit_store: WorkunitStore::new(false, log::Level::Debug),
      build_id: String::default(),
      run_id: RunId(0),
    }
  }
}

impl Context {
  pub fn new(workunit_store: WorkunitStore, build_id: String, run_id: RunId) -> Context {
    Context {
      workunit_store,
      build_id,
      run_id,
    }
  }
}

#[async_trait]
pub trait CommandRunner: Send + Sync {
  ///
  /// Submit a request for execution on the underlying runtime, and return
  /// a future for it.
  ///
  async fn run(
    &self,
    context: Context,
    workunit: &mut RunningWorkunit,
    req: Process,
  ) -> Result<FallibleProcessResultWithPlatform, String>;
}

// TODO(#8513) possibly move to the MEPR struct, or to the hashing crate?
pub fn digest(process: &Process, metadata: &ProcessMetadata) -> Digest {
  let (_, _, execute_request) =
    crate::remote::make_execute_request(process, metadata.clone()).unwrap();
  execute_request.action_digest.unwrap().try_into().unwrap()
}

#[cfg(test)]
mod tests;
