// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashSet};
use std::convert::{Into, TryInto};
use std::future::Future;
use std::io::Read;
use std::ops::{Deref, DerefMut};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use crate::core::Failure;
use crate::intrinsics::Intrinsics;
use crate::nodes::{NodeKey, WrappedNode};
use crate::session::{Session, Sessions};
use crate::tasks::{Rule, Tasks};
use crate::types::Types;

use fs::{safe_create_dir_all_ioerror, GitignoreStyleExcludes, PosixFS};
use graph::{self, EntryId, Graph, InvalidationResult, NodeContext};
use log::info;
use parking_lot::Mutex;
use process_execution::{
  self, BoundedCommandRunner, CommandRunner, NamedCaches, Platform, ProcessMetadata,
  RemoteCacheWarningsBehavior,
};
use regex::Regex;
use rule_graph::RuleGraph;
use sharded_lmdb::ShardedLmdb;
use store::{self, Store};
use task_executor::Executor;
use uuid::Uuid;
use watch::{Invalidatable, InvalidationWatcher};

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
  pub command_runner: Box<dyn process_execution::CommandRunner>,
  pub http_client: reqwest::Client,
  pub vfs: PosixFS,
  pub watcher: Arc<InvalidationWatcher>,
  pub build_root: PathBuf,
  pub local_parallelism: usize,
  pub sessions: Sessions,
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
  pub cache_warnings_behavior: RemoteCacheWarningsBehavior,
  pub cache_eager_fetch: bool,
  pub execution_extra_platform_properties: Vec<(String, String)>,
  pub execution_headers: BTreeMap<String, String>,
  pub execution_overall_deadline: Duration,
}

#[derive(Clone, Debug)]
pub struct ExecutionStrategyOptions {
  pub local_parallelism: usize,
  pub remote_parallelism: usize,
  pub local_cleanup: bool,
  pub local_cache: bool,
  pub remote_cache_read: bool,
  pub remote_cache_write: bool,
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
        root_ca_certs.clone(),
        remoting_opts.store_headers.clone(),
        remoting_opts.store_chunk_bytes,
        remoting_opts.store_chunk_upload_timeout,
        remoting_opts.store_rpc_retries,
      )
    } else {
      Ok(local_only)
    }
  }

  fn make_command_runner(
    full_store: &Store,
    remote_store_address: &Option<String>,
    executor: &Executor,
    local_execution_root_dir: &Path,
    named_caches_dir: &Path,
    local_store_options: &LocalStoreOptions,
    process_execution_metadata: &ProcessMetadata,
    root_ca_certs: &Option<Vec<u8>>,
    exec_strategy_opts: &ExecutionStrategyOptions,
    remoting_opts: &RemotingOptions,
  ) -> Result<Box<dyn CommandRunner>, String> {
    let remote_caching_used =
      exec_strategy_opts.remote_cache_read || exec_strategy_opts.remote_cache_write;

    // If remote caching is used with eager_fetch, we do not want to use the remote store
    // with the local command runner. This reduces the surface area of where the remote store is
    // used to only be the remote cache command runner.
    let store_for_local_runner = if remote_caching_used && remoting_opts.cache_eager_fetch {
      full_store.clone().into_local_only()
    } else {
      full_store.clone()
    };
    let local_command_runner = Box::new(BoundedCommandRunner::new(
      Box::new(process_execution::local::CommandRunner::new(
        store_for_local_runner,
        executor.clone(),
        local_execution_root_dir.to_path_buf(),
        NamedCaches::new(named_caches_dir.to_path_buf()),
        exec_strategy_opts.local_cleanup,
      )),
      exec_strategy_opts.local_parallelism,
    ));

    // Possibly either add the remote execution runner or the remote cache runner.
    // `global_options.py` already validates that both are not set at the same time.
    let maybe_remote_enabled_command_runner: Box<dyn CommandRunner> =
      if remoting_opts.execution_enable {
        Box::new(BoundedCommandRunner::new(
          Box::new(process_execution::remote::CommandRunner::new(
            // We unwrap because global_options.py will have already validated these are defined.
            remoting_opts.execution_address.as_ref().unwrap(),
            remoting_opts.store_address.as_ref().unwrap(),
            process_execution_metadata.clone(),
            root_ca_certs.clone(),
            remoting_opts.execution_headers.clone(),
            full_store.clone(),
            // TODO if we ever want to configure the remote platform to be something else we
            // need to take an option all the way down here and into the remote::CommandRunner struct.
            Platform::Linux,
            remoting_opts.execution_overall_deadline,
            Duration::from_millis(100),
          )?),
          exec_strategy_opts.remote_parallelism,
        ))
      } else if remote_caching_used {
        Box::new(process_execution::remote_cache::CommandRunner::new(
          local_command_runner.into(),
          process_execution_metadata.clone(),
          executor.clone(),
          full_store.clone(),
          remote_store_address.as_ref().unwrap(),
          root_ca_certs.clone(),
          remoting_opts.store_headers.clone(),
          Platform::current()?,
          exec_strategy_opts.remote_cache_read,
          exec_strategy_opts.remote_cache_write,
          remoting_opts.cache_warnings_behavior,
          remoting_opts.cache_eager_fetch,
        )?)
      } else {
        local_command_runner
      };

    // Possibly use the local cache runner, regardless of remote execution/caching.
    let maybe_local_cached_command_runner = if exec_strategy_opts.local_cache {
      let process_execution_store = ShardedLmdb::new(
        local_store_options.store_dir.join("processes"),
        local_store_options.process_cache_max_size_bytes,
        executor.clone(),
        local_store_options.lease_time,
        local_store_options.shard_count,
      )
      .map_err(|err| format!("Could not initialize store for process cache: {:?}", err))?;
      Box::new(process_execution::cache::CommandRunner::new(
        maybe_remote_enabled_command_runner.into(),
        process_execution_store,
        full_store.clone(),
        process_execution_metadata.clone(),
      ))
    } else {
      maybe_remote_enabled_command_runner
    };

    Ok(maybe_local_cached_command_runner)
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
    )
    .map_err(|e| format!("Could not initialize Store: {:?}", e))?;

    let store = if (exec_strategy_opts.remote_cache_read || exec_strategy_opts.remote_cache_write)
      && remoting_opts.cache_eager_fetch
    {
      // In remote cache mode with eager fetching, the only interaction with the remote CAS
      // should be through the remote cache code paths. Thus, the store seen by the rest of the
      // code base should be the local-only store.
      full_store.clone().into_local_only()
    } else {
      // Otherwise, the remote CAS should be visible everywhere.
      full_store.clone()
    };

    let process_execution_metadata = ProcessMetadata {
      instance_name: remoting_opts.instance_name.clone(),
      cache_key_gen_version: remoting_opts.execution_process_cache_namespace.clone(),
      platform_properties: remoting_opts.execution_extra_platform_properties.clone(),
    };

    let command_runner = Self::make_command_runner(
      &full_store,
      &remoting_opts.store_address,
      &executor,
      &local_execution_root_dir,
      &named_caches_dir,
      &local_store_options,
      &process_execution_metadata,
      &root_ca_certs,
      &exec_strategy_opts,
      &remoting_opts,
    )?;

    let graph = Arc::new(InvalidatableGraph(Graph::new()));

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

    let watcher = InvalidationWatcher::new(executor.clone(), build_root.clone(), ignorer.clone())?;
    watcher.start(&graph);

    let sessions = Sessions::new(&executor)?;

    Ok(Core {
      graph,
      tasks,
      rule_graph,
      types,
      intrinsics,
      executor: executor.clone(),
      store,
      command_runner,
      http_client,
      // TODO: Errors in initialization should definitely be exposed as python
      // exceptions, rather than as panics.
      vfs: PosixFS::new(&build_root, ignorer, executor)
        .map_err(|e| format!("Could not initialize VFS: {:?}", e))?,
      build_root,
      watcher,
      local_parallelism: exec_strategy_opts.local_parallelism,
      sessions,
    })
  }

  pub fn store(&self) -> Store {
    self.store.clone()
  }
}

pub struct InvalidatableGraph(Graph<NodeKey>);

impl Invalidatable for InvalidatableGraph {
  fn invalidate(&self, paths: &HashSet<PathBuf>, caller: &str) -> usize {
    let InvalidationResult { cleared, dirtied } = self.invalidate_from_roots(move |node| {
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
      self.invalidate_from_roots(|node| node.fs_subject().is_some());
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
  run_id: Uuid,
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
      stats: Arc::default(),
    }
  }

  ///
  /// Get the future value for the given Node implementation.
  ///
  pub async fn get<N: WrappedNode>(&self, node: N) -> Result<N::Item, Failure> {
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
}

impl NodeContext for Context {
  type Node = NodeKey;
  type RunId = Uuid;

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
