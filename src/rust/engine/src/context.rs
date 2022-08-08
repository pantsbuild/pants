// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::cmp::max;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::convert::{Into, TryInto};
use std::future::Future;
use std::io::Read;
use std::ops::{Deref, DerefMut};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use crate::intrinsics::Intrinsics;
use crate::nodes::{ExecuteProcess, NodeKey, NodeOutput, NodeResult, WrappedNode};
use crate::python::{throw, Failure};
use crate::session::{Session, Sessions};
use crate::tasks::{Rule, Tasks};
use crate::types::Types;

use async_oncecell::OnceCell;
use cache::PersistentCache;
use fs::{safe_create_dir_all_ioerror, GitignoreStyleExcludes, PosixFS};
use graph::{self, EntryId, Graph, InvalidationResult, NodeContext};
use hashing::Digest;
use log::info;
use parking_lot::Mutex;
use process_execution::{
  self, bounded, local, nailgun, remote, remote_cache, CacheContentBehavior, CommandRunner,
  ImmutableInputs, NamedCaches, Platform, ProcessMetadata, RemoteCacheWarningsBehavior,
};
use protos::gen::build::bazel::remote::execution::v2::ServerCapabilities;
use regex::Regex;
use rule_graph::RuleGraph;
use store::{self, Store};
use task_executor::Executor;
use watch::{Invalidatable, InvalidationWatcher};
use workunit_store::{Metric, RunId, RunningWorkunit};

// The reqwest crate has no support for ingesting multiple certificates in a single file,
// and requires single PEM blocks. There is a crate (https://crates.io/crates/pem) that can decode
// multiple certificates from a single buffer, but it is not suitable for our use because we don't
// want to decode the certificates, but rather pass them as source to reqwest. That crate also
// inappropriately squelches errors.
//
// Instead we make our own use of a copy of the regex used by the pem crate.  Note:
//   - The leading (?s) which sets the flag to allow . to match \n.
//   - The use of ungreedy repetition via .*?, so we get shortest instead of longest matches.
const PEM_RE_STR: &str =
  r"(?s)-----BEGIN (?P<begin>.*?)-----\s*(?P<data>.*?)-----END (?P<end>.*?)-----\s*";

///
/// The core context shared (via Arc) between the Scheduler and the Context objects of
/// all running Nodes.
///
pub struct Core {
  pub graph: Arc<InvalidatableGraph>,
  pub tasks: Tasks,
  pub rule_graph: RuleGraph<Rule>,
  pub types: Types,
  pub intrinsics: Intrinsics,
  pub executor: Executor,
  store: Store,
  /// The CommandRunners to use for execution, in ascending order of reliability (for the purposes
  /// of backtracking). For performance reasons, caching `CommandRunners` might skip validation of
  /// their outputs, and so should be listed before uncached `CommandRunners`.
  pub command_runners: Vec<Arc<dyn CommandRunner>>,
  pub http_client: reqwest::Client,
  pub local_cache: PersistentCache,
  pub vfs: PosixFS,
  pub watcher: Option<Arc<InvalidationWatcher>>,
  pub build_root: PathBuf,
  pub local_parallelism: usize,
  pub graceful_shutdown_timeout: Duration,
  pub sessions: Sessions,
  pub named_caches: NamedCaches,
  pub immutable_inputs: ImmutableInputs,
  pub local_execution_root_dir: PathBuf,
}

#[derive(Clone, Debug)]
pub struct RemotingOptions {
  pub execution_enable: bool,
  pub store_address: Option<String>,
  pub execution_address: Option<String>,
  pub execution_process_cache_namespace: Option<String>,
  pub instance_name: Option<String>,
  pub root_ca_certs_path: Option<PathBuf>,
  pub store_headers: BTreeMap<String, String>,
  pub store_chunk_bytes: usize,
  pub store_chunk_upload_timeout: Duration,
  pub store_rpc_retries: usize,
  pub store_rpc_concurrency: usize,
  pub store_batch_api_size_limit: usize,
  pub cache_warnings_behavior: RemoteCacheWarningsBehavior,
  pub cache_content_behavior: CacheContentBehavior,
  pub cache_rpc_concurrency: usize,
  pub cache_read_timeout: Duration,
  pub execution_extra_platform_properties: Vec<(String, String)>,
  pub execution_headers: BTreeMap<String, String>,
  pub execution_overall_deadline: Duration,
  pub execution_rpc_concurrency: usize,
}

#[derive(Clone, Debug)]
pub struct ExecutionStrategyOptions {
  pub local_parallelism: usize,
  pub remote_parallelism: usize,
  pub local_keep_sandboxes: local::KeepSandboxes,
  pub local_cache: bool,
  pub local_enable_nailgun: bool,
  pub remote_cache_read: bool,
  pub remote_cache_write: bool,
  pub child_max_memory: usize,
  pub child_default_memory: usize,
  pub graceful_shutdown_timeout: Duration,
}

#[derive(Clone, Debug)]
pub struct LocalStoreOptions {
  pub store_dir: PathBuf,
  pub process_cache_max_size_bytes: usize,
  pub files_max_size_bytes: usize,
  pub directories_max_size_bytes: usize,
  pub lease_time: Duration,
  pub shard_count: u8,
}

impl From<&LocalStoreOptions> for store::LocalOptions {
  fn from(lso: &LocalStoreOptions) -> Self {
    Self {
      files_max_size_bytes: lso.files_max_size_bytes,
      directories_max_size_bytes: lso.directories_max_size_bytes,
      lease_time: lso.lease_time,
      shard_count: lso.shard_count,
    }
  }
}

impl Core {
  fn make_store(
    executor: &Executor,
    local_store_options: &LocalStoreOptions,
    enable_remote: bool,
    remoting_opts: &RemotingOptions,
    remote_store_address: &Option<String>,
    root_ca_certs: &Option<Vec<u8>>,
    capabilities_cell_opt: Option<Arc<OnceCell<ServerCapabilities>>>,
  ) -> Result<Store, String> {
    let local_only = Store::local_only_with_options(
      executor.clone(),
      local_store_options.store_dir.clone(),
      local_store_options.into(),
    )?;
    if enable_remote {
      let remote_store_address = remote_store_address
        .as_ref()
        .ok_or("Remote store required, but none configured")?;
      local_only.into_with_remote(
        remote_store_address,
        remoting_opts.instance_name.clone(),
        grpc_util::tls::Config::new_without_mtls(root_ca_certs.clone()),
        remoting_opts.store_headers.clone(),
        remoting_opts.store_chunk_bytes,
        remoting_opts.store_chunk_upload_timeout,
        remoting_opts.store_rpc_retries,
        remoting_opts.store_rpc_concurrency,
        capabilities_cell_opt,
        remoting_opts.store_batch_api_size_limit,
      )
    } else {
      Ok(local_only)
    }
  }

  ///
  /// Make the innermost / leaf runner. Will have concurrency control and process pooling, but
  /// will not have caching.
  ///
  fn make_leaf_runner(
    full_store: &Store,
    local_runner_store: &Store,
    executor: &Executor,
    local_execution_root_dir: &Path,
    immutable_inputs: &ImmutableInputs,
    named_caches: &NamedCaches,
    process_execution_metadata: &ProcessMetadata,
    root_ca_certs: &Option<Vec<u8>>,
    exec_strategy_opts: &ExecutionStrategyOptions,
    remoting_opts: &RemotingOptions,
    capabilities_cell_opt: Option<Arc<OnceCell<ServerCapabilities>>>,
  ) -> Result<Arc<dyn CommandRunner>, String> {
    let (runner, parallelism): (Box<dyn CommandRunner>, usize) = if remoting_opts.execution_enable {
      (
        Box::new(remote::CommandRunner::new(
          // We unwrap because global_options.py will have already validated these are defined.
          remoting_opts.execution_address.as_ref().unwrap(),
          process_execution_metadata.clone(),
          root_ca_certs.clone(),
          remoting_opts.execution_headers.clone(),
          full_store.clone(),
          // TODO if we ever want to configure the remote platform to be something else we
          // need to take an option all the way down here and into the remote::CommandRunner struct.
          Platform::Linux_x86_64,
          remoting_opts.execution_overall_deadline,
          Duration::from_millis(100),
          remoting_opts.execution_rpc_concurrency,
          capabilities_cell_opt,
        )?),
        exec_strategy_opts.remote_parallelism,
      )
    } else {
      let local_command_runner = local::CommandRunner::new(
        local_runner_store.clone(),
        executor.clone(),
        local_execution_root_dir.to_path_buf(),
        named_caches.clone(),
        immutable_inputs.clone(),
        exec_strategy_opts.local_keep_sandboxes,
      );

      let runner: Box<dyn CommandRunner> = if exec_strategy_opts.local_enable_nailgun {
        // We set the nailgun pool size to the number of instances that fit within the memory
        // parameters configured when a max child process memory has been given.
        // Otherwise, pool size will be double of the local parallelism so we can always keep
        // a jvm warmed up.
        let pool_size: usize = if exec_strategy_opts.child_max_memory > 0 {
          max(
            1,
            exec_strategy_opts.child_max_memory / exec_strategy_opts.child_default_memory,
          )
        } else {
          exec_strategy_opts.local_parallelism * 2
        };

        Box::new(nailgun::CommandRunner::new(
          local_command_runner,
          local_execution_root_dir.to_path_buf(),
          local_runner_store.clone(),
          executor.clone(),
          pool_size,
        ))
      } else {
        Box::new(local_command_runner)
      };

      (runner, exec_strategy_opts.local_parallelism)
    };

    Ok(Arc::new(bounded::CommandRunner::new(
      executor,
      runner,
      parallelism,
    )))
  }

  ///
  /// Creates a single stack of cached runners around the given "leaf" CommandRunner.
  ///
  /// The given cache read/write flags override the relevant cache flags to allow this method
  /// to be called with all cache reads disabled, regardless of their configured values.
  ///
  fn make_cached_runner(
    mut runner: Arc<dyn CommandRunner>,
    full_store: &Store,
    executor: &Executor,
    local_cache: &PersistentCache,
    process_execution_metadata: &ProcessMetadata,
    root_ca_certs: &Option<Vec<u8>>,
    remoting_opts: &RemotingOptions,
    remote_cache_read: bool,
    remote_cache_write: bool,
    local_cache_read: bool,
    local_cache_write: bool,
  ) -> Result<Arc<dyn CommandRunner>, String> {
    // TODO: Until we can deprecate letting the flag default, we implicitly default
    // cache_content_behavior when remote execution is in use.
    let cache_content_behavior = if remoting_opts.execution_enable {
      CacheContentBehavior::Defer
    } else {
      remoting_opts.cache_content_behavior
    };
    if remote_cache_read || remote_cache_write {
      runner = Arc::new(remote_cache::CommandRunner::new(
        runner,
        process_execution_metadata.clone(),
        executor.clone(),
        full_store.clone(),
        remoting_opts.store_address.as_ref().unwrap(),
        root_ca_certs.clone(),
        remoting_opts.store_headers.clone(),
        Platform::current()?,
        remote_cache_read,
        remote_cache_write,
        remoting_opts.cache_warnings_behavior,
        cache_content_behavior,
        remoting_opts.cache_rpc_concurrency,
        remoting_opts.cache_read_timeout,
      )?);
    }

    if local_cache_read || local_cache_write {
      runner = Arc::new(process_execution::cache::CommandRunner::new(
        runner,
        local_cache.clone(),
        full_store.clone(),
        local_cache_read,
        cache_content_behavior,
        process_execution_metadata.clone(),
      ));
    }

    Ok(runner)
  }

  ///
  /// Creates the stack of CommandRunners for the purposes of backtracking.
  ///
  fn make_command_runners(
    full_store: &Store,
    local_runner_store: &Store,
    executor: &Executor,
    local_cache: &PersistentCache,
    local_execution_root_dir: &Path,
    immutable_inputs: &ImmutableInputs,
    named_caches: &NamedCaches,
    process_execution_metadata: &ProcessMetadata,
    root_ca_certs: &Option<Vec<u8>>,
    exec_strategy_opts: &ExecutionStrategyOptions,
    remoting_opts: &RemotingOptions,
    capabilities_cell_opt: Option<Arc<OnceCell<ServerCapabilities>>>,
  ) -> Result<Vec<Arc<dyn CommandRunner>>, String> {
    let leaf_runner = Self::make_leaf_runner(
      full_store,
      local_runner_store,
      executor,
      local_execution_root_dir,
      immutable_inputs,
      named_caches,
      process_execution_metadata,
      root_ca_certs,
      exec_strategy_opts,
      remoting_opts,
      capabilities_cell_opt,
    )?;

    // TODO: Until we can deprecate letting remote-cache-{read,write} default, we implicitly
    // enable them when remote execution is in use.
    let remote_cache_read = exec_strategy_opts.remote_cache_read || remoting_opts.execution_enable;
    let remote_cache_write =
      exec_strategy_opts.remote_cache_write || remoting_opts.execution_enable;
    let local_cache_read_write = exec_strategy_opts.local_cache;

    let make_cached_runner = |should_cache_read: bool| -> Result<Arc<dyn CommandRunner>, String> {
      Self::make_cached_runner(
        leaf_runner.clone(),
        full_store,
        executor,
        local_cache,
        process_execution_metadata,
        root_ca_certs,
        remoting_opts,
        remote_cache_read && should_cache_read,
        remote_cache_write,
        local_cache_read_write && should_cache_read,
        local_cache_read_write,
      )
    };

    // The first attempt is always with all caches.
    let mut runners = vec![make_cached_runner(true)?];
    // If any cache is both readable and writable, we additionally add a backtracking attempt which
    // disables all cache reads.
    if (remote_cache_read && remote_cache_write) || local_cache_read_write {
      runners.push(make_cached_runner(false)?);
    }

    Ok(runners)
  }

  fn load_certificates(
    ca_certs_path: Option<PathBuf>,
  ) -> Result<Vec<reqwest::Certificate>, String> {
    let certs = match ca_certs_path {
      Some(ref path) => {
        let mut content = String::new();
        std::fs::File::open(path)
          .and_then(|mut f| f.read_to_string(&mut content))
          .map_err(|err| {
            format!(
              "Error reading root CA certs file {}: {}",
              path.display(),
              err
            )
          })?;
        let pem_re = Regex::new(PEM_RE_STR).unwrap();
        let certs_res: Result<Vec<reqwest::Certificate>, _> = pem_re
          .find_iter(&content)
          .map(|mat| reqwest::Certificate::from_pem(mat.as_str().as_bytes()))
          .collect();
        certs_res.map_err(|err| {
          format!(
            "Error parsing PEM from root CA certs file {}: {}",
            path.display(),
            err
          )
        })?
      }
      None => Vec::new(),
    };
    Ok(certs)
  }

  pub fn new(
    executor: Executor,
    tasks: Tasks,
    types: Types,
    intrinsics: Intrinsics,
    build_root: PathBuf,
    ignore_patterns: Vec<String>,
    use_gitignore: bool,
    watch_filesystem: bool,
    local_execution_root_dir: PathBuf,
    named_caches_dir: PathBuf,
    ca_certs_path: Option<PathBuf>,
    local_store_options: LocalStoreOptions,
    remoting_opts: RemotingOptions,
    exec_strategy_opts: ExecutionStrategyOptions,
  ) -> Result<Core, String> {
    // We re-use these certs for both the execution and store service; they're generally tied together.
    let root_ca_certs = if let Some(ref path) = remoting_opts.root_ca_certs_path {
      Some(
        std::fs::read(path)
          .map_err(|err| format!("Error reading root CA certs file {:?}: {}", path, err))?,
      )
    } else {
      None
    };

    let need_remote_store = remoting_opts.execution_enable
      || exec_strategy_opts.remote_cache_read
      || exec_strategy_opts.remote_cache_write;

    // If the remote store and remote execution server are the same (address and headers),
    // then share the capabilities cache between them to avoid duplicate GetCapabilities calls.
    let capabilities_cell_opt = if need_remote_store
      && remoting_opts.execution_address == remoting_opts.store_address
      && remoting_opts.execution_headers == remoting_opts.store_headers
    {
      Some(Arc::new(OnceCell::new()))
    } else {
      None
    };

    safe_create_dir_all_ioerror(&local_store_options.store_dir).map_err(|e| {
      format!(
        "Error making directory {:?}: {:?}",
        local_store_options.store_dir, e
      )
    })?;
    let full_store = Self::make_store(
      &executor,
      &local_store_options,
      need_remote_store,
      &remoting_opts,
      &remoting_opts.store_address,
      &root_ca_certs,
      capabilities_cell_opt.clone(),
    )
    .map_err(|e| format!("Could not initialize Store: {:?}", e))?;

    let local_cache = PersistentCache::new(
      &local_store_options.store_dir,
      // TODO: Rename.
      local_store_options.process_cache_max_size_bytes,
      executor.clone(),
      local_store_options.lease_time,
      local_store_options.shard_count,
    )?;

    let store = if (exec_strategy_opts.remote_cache_read || exec_strategy_opts.remote_cache_write)
      && remoting_opts.cache_content_behavior == CacheContentBehavior::Fetch
    {
      // In remote cache mode with eager fetching, the only interaction with the remote CAS
      // should be through the remote cache code paths. Thus, the store seen by the rest of the
      // code base should be the local-only store.
      full_store.clone().into_local_only()
    } else {
      // Otherwise, the remote CAS should be visible everywhere.
      full_store.clone()
    };

    let immutable_inputs = ImmutableInputs::new(store.clone(), &local_execution_root_dir)?;
    let named_caches = NamedCaches::new(named_caches_dir);
    let process_execution_metadata = ProcessMetadata {
      instance_name: remoting_opts.instance_name.clone(),
      cache_key_gen_version: remoting_opts.execution_process_cache_namespace.clone(),
      platform_properties: remoting_opts.execution_extra_platform_properties.clone(),
    };

    let command_runners = Self::make_command_runners(
      &full_store,
      &store,
      &executor,
      &local_cache,
      &local_execution_root_dir,
      &immutable_inputs,
      &named_caches,
      &process_execution_metadata,
      &root_ca_certs,
      &exec_strategy_opts,
      &remoting_opts,
      capabilities_cell_opt,
    )?;
    log::debug!("Using {command_runners:?} for process execution.");

    let graph = Arc::new(InvalidatableGraph(Graph::new(executor.clone())));

    // These certs are for downloads, not to be confused with the ones used for remoting.
    let ca_certs = Self::load_certificates(ca_certs_path)?;

    let http_client_builder = ca_certs
      .iter()
      .fold(reqwest::Client::builder(), |builder, cert| {
        builder.add_root_certificate(cert.clone())
      });
    let http_client = http_client_builder
      .build()
      .map_err(|err| format!("Error building HTTP client: {}", err))?;
    let rule_graph = RuleGraph::new(tasks.rules().clone(), tasks.queries().clone())?;

    let gitignore_file = if use_gitignore {
      let gitignore_path = build_root.join(".gitignore");
      if Path::is_file(&gitignore_path) {
        Some(gitignore_path)
      } else {
        None
      }
    } else {
      None
    };
    let ignorer =
      GitignoreStyleExcludes::create_with_gitignore_file(ignore_patterns, gitignore_file)
        .map_err(|e| format!("Could not parse build ignore patterns: {:?}", e))?;

    let watcher = if watch_filesystem {
      let w = InvalidationWatcher::new(executor.clone(), build_root.clone(), ignorer.clone())?;
      w.start(&graph);
      Some(w)
    } else {
      None
    };

    let sessions = Sessions::new(&executor)?;

    Ok(Core {
      graph,
      tasks,
      rule_graph,
      types,
      intrinsics,
      executor: executor.clone(),
      store,
      command_runners,
      http_client,
      local_cache,
      vfs: PosixFS::new(&build_root, ignorer, executor)
        .map_err(|e| format!("Could not initialize Vfs: {:?}", e))?,
      build_root,
      watcher,
      local_parallelism: exec_strategy_opts.local_parallelism,
      graceful_shutdown_timeout: exec_strategy_opts.graceful_shutdown_timeout,
      sessions,
      named_caches,
      immutable_inputs,
      local_execution_root_dir,
    })
  }

  pub fn store(&self) -> Store {
    self.store.clone()
  }

  ///
  /// Shuts down this Core.
  ///
  pub async fn shutdown(&self, timeout: Duration) {
    // Shutdown the Sessions, which will prevent new work from starting and then await any ongoing
    // work.
    if let Err(msg) = self.sessions.shutdown(timeout).await {
      log::warn!("During shutdown: {}", msg);
    }
    // Then clear the Graph to ensure that drop handlers run (particularly for running processes).
    self.graph.clear();
  }
}

pub struct InvalidatableGraph(Graph<NodeKey>);

impl Invalidatable for InvalidatableGraph {
  fn invalidate(&self, paths: &HashSet<PathBuf>, caller: &str) -> usize {
    let InvalidationResult { cleared, dirtied } = self.invalidate_from_roots(false, move |node| {
      if let Some(fs_subject) = node.fs_subject() {
        paths.contains(fs_subject)
      } else {
        false
      }
    });
    info!(
      "{} invalidation: cleared {} and dirtied {} nodes for: {:?}",
      caller, cleared, dirtied, paths
    );
    cleared + dirtied
  }

  fn invalidate_all(&self, caller: &str) -> usize {
    let InvalidationResult { cleared, dirtied } =
      self.invalidate_from_roots(false, |node| node.fs_subject().is_some());
    info!(
      "{} invalidation: cleared {} and dirtied {} nodes for all paths",
      caller, cleared, dirtied
    );
    cleared + dirtied
  }
}

impl Deref for InvalidatableGraph {
  type Target = Graph<NodeKey>;

  fn deref(&self) -> &Graph<NodeKey> {
    &self.0
  }
}

#[derive(Clone)]
pub struct Context {
  entry_id: Option<EntryId>,
  pub core: Arc<Core>,
  pub session: Session,
  run_id: RunId,
  /// The number of attempts which have been made to backtrack to a particular ExecuteProcess node.
  ///
  /// Presence in this map at process runtime indicates that the process is being retried, and that
  /// there was something invalid or unusable about previous attempts. Successive attempts should
  /// run in a different mode (skipping caches, etc) to attempt to produce a valid result.
  backtrack_levels: Arc<Mutex<HashMap<ExecuteProcess, usize>>>,
  /// The Digests that we have successfully invalidated a Node for.
  backtrack_digests: Arc<Mutex<HashSet<Digest>>>,
  stats: Arc<Mutex<graph::Stats>>,
}

impl Context {
  pub fn new(core: Arc<Core>, session: Session) -> Context {
    let run_id = session.run_id();
    Context {
      entry_id: None,
      core,
      session,
      run_id,
      backtrack_levels: Arc::default(),
      backtrack_digests: Arc::default(),
      stats: Arc::default(),
    }
  }

  ///
  /// Get the future value for the given Node implementation.
  ///
  pub async fn get<N: WrappedNode>(&self, node: N) -> NodeResult<N::Item> {
    let node_result = self
      .core
      .graph
      .get(self.entry_id, self, node.into())
      .await?;
    Ok(
      node_result
        .try_into()
        .unwrap_or_else(|_| panic!("A Node implementation was ambiguous.")),
    )
  }

  ///
  /// If the given Result is a Failure::MissingDigest, attempts to invalidate the Node which was
  /// the source of the Digest, potentially causing indirect retry of the Result.
  ///
  /// If we successfully locate and restart the source of the Digest, converts the Result into a
  /// `Failure::Invalidated`, which will cause retry at some level above us.
  ///
  pub fn maybe_backtrack(
    &self,
    result: NodeResult<NodeOutput>,
    workunit: &mut RunningWorkunit,
  ) -> NodeResult<NodeOutput> {
    let digest = if let Err(Failure::MissingDigest(_, d)) = result.as_ref() {
      *d
    } else {
      return result;
    };

    // Locate live source(s) of this Digest and their backtracking levels.
    // TODO: Currently needs a combination of `visit_live` and `invalidate_from_roots` because
    // `invalidate_from_roots` cannot view `Node` results. Would be more efficient as a merged
    // method.
    let mut candidate_roots = Vec::new();
    self.core.graph.visit_live(self, |k, v| match k {
      NodeKey::ExecuteProcess(p) if v.digests().contains(&digest) => {
        if let NodeOutput::ProcessResult(pr) = v {
          candidate_roots.push((p.clone(), pr.backtrack_level));
        }
      }
      _ => (),
    });

    if candidate_roots.is_empty() {
      // If there are no live sources of the Digest, see whether any have already been invalidated
      // by other consumers.
      if self.backtrack_digests.lock().get(&digest).is_some() {
        // Some other consumer has already identified and invalidated the source of this Digest: we
        // can wait for the attempt to complete.
        return Err(Failure::Invalidated);
      } else {
        // There are no live or invalidated sources of this Digest. Directly fail.
        return result.map_err(|e| {
          throw(format!(
            "Could not identify a process to backtrack to for: {e}"
          ))
        });
      }
    } else {
      // We have identified a Node to backtrack on. Record it.
      self.backtrack_digests.lock().insert(digest);
    }

    // Attempt to trigger backtrack attempts for the matched Nodes. It's possible that we are not
    // the first consumer to notice that this Node needs to backtrack, so we only actually report
    // that we're backtracking if the new level is an increase from the old level.
    let roots = candidate_roots
      .into_iter()
      .filter_map(|(root, invalid_level)| {
        let next_level = invalid_level + 1;
        let maybe_new_level = {
          let mut backtrack_levels = self.backtrack_levels.lock();
          if let Some(old_backtrack_level) = backtrack_levels.get_mut(&root) {
            if next_level > *old_backtrack_level {
              *old_backtrack_level = next_level;
              Some(next_level)
            } else {
              None
            }
          } else {
            backtrack_levels.insert((*root).clone(), next_level);
            Some(next_level)
          }
        };
        if let Some(new_level) = maybe_new_level {
          workunit.increment_counter(Metric::BacktrackAttempts, 1);
          let description = &root.process.description;
          log::warn!(
            "Making attempt {new_level} to backtrack and retry `{description}`, due to \
              missing digest {digest:?}."
          );
          Some(root)
        } else {
          None
        }
      })
      .collect::<HashSet<_>>();

    // Invalidate the matched roots.
    self
      .core
      .graph
      .invalidate_from_roots(true, move |node| match node {
        NodeKey::ExecuteProcess(p) => roots.contains(p),
        _ => false,
      });

    // We invalidated a Node, and the caller (at some level above us in the stack) should retry.
    // Complete this node with the Invalidated state.
    // TODO: Differentiate the reasons for Invalidation (filesystem changes vs missing digests) to
    // improve warning messages. See https://github.com/pantsbuild/pants/issues/15867
    Err(Failure::Invalidated)
  }

  ///
  /// Called before executing a process to determine whether it is backtracking.
  ///
  /// A process which has not been marked backtracking will always return 0.
  ///
  pub fn maybe_start_backtracking(&self, node: &ExecuteProcess) -> usize {
    self.backtrack_levels.lock().get(node).cloned().unwrap_or(0)
  }
}

impl NodeContext for Context {
  type Node = NodeKey;
  type RunId = RunId;

  fn stats<'a>(&'a self) -> Box<dyn DerefMut<Target = graph::Stats> + 'a> {
    Box::new(self.stats.lock())
  }

  ///
  /// Clones this Context for a new EntryId. Because the Core of the context is an Arc, this
  /// is a shallow clone.
  ///
  fn clone_for(&self, entry_id: EntryId) -> Context {
    Context {
      entry_id: Some(entry_id),
      core: self.core.clone(),
      session: self.session.clone(),
      run_id: self.run_id,
      backtrack_levels: self.backtrack_levels.clone(),
      backtrack_digests: self.backtrack_digests.clone(),
      stats: self.stats.clone(),
    }
  }

  fn run_id(&self) -> &Self::RunId {
    &self.run_id
  }

  fn graph(&self) -> &Graph<NodeKey> {
    &self.core.graph
  }

  fn spawn<F>(&self, future: F)
  where
    F: Future<Output = ()> + Send + 'static,
  {
    let _join = self.core.executor.spawn(future);
  }
}
