// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashSet};
use std::convert::{Into, TryInto};
use std::future::Future;
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use crate::core::{Failure, TypeId};
use crate::intrinsics::Intrinsics;
use crate::nodes::{NodeKey, WrappedNode};
use crate::scheduler::Session;
use crate::tasks::{Rule, Tasks};
use crate::types::Types;

use fs::{safe_create_dir_all_ioerror, GitignoreStyleExcludes, PosixFS};
use graph::{EntryId, Graph, InvalidationResult, NodeContext, RunToken};
use log::info;
use process_execution::{
  self, speculate::SpeculatingCommandRunner, BoundedCommandRunner, CommandRunner, NamedCaches,
  Platform, ProcessMetadata,
};
use rand::seq::SliceRandom;
use rule_graph::RuleGraph;
use sharded_lmdb::{ShardedLmdb, DEFAULT_LEASE_TIME};
use store::Store;
use task_executor::Executor;
use uuid::Uuid;
use watch::{Invalidatable, InvalidationWatcher};

const GIGABYTES: usize = 1024 * 1024 * 1024;

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
}

#[derive(Clone, Debug)]
pub struct RemotingOptions {
  pub execution_enable: bool,
  pub store_servers: Vec<String>,
  pub execution_server: Option<String>,
  pub execution_process_cache_namespace: Option<String>,
  pub instance_name: Option<String>,
  pub root_ca_certs_path: Option<PathBuf>,
  pub oauth_bearer_token_path: Option<PathBuf>,
  pub store_thread_count: usize,
  pub store_chunk_bytes: usize,
  pub store_chunk_upload_timeout: Duration,
  pub store_rpc_retries: usize,
  pub store_connection_limit: usize,
  pub execution_extra_platform_properties: Vec<(String, String)>,
  pub execution_headers: BTreeMap<String, String>,
  pub execution_overall_deadline: Duration,
}

#[derive(Clone, Debug)]
pub struct ExecutionStrategyOptions {
  pub local_parallelism: usize,
  pub remote_parallelism: usize,
  pub cleanup_local_dirs: bool,
  pub speculation_delay: Duration,
  pub speculation_strategy: String,
  pub use_local_cache: bool,
  pub local_enable_nailgun: bool,
}

impl Core {
  pub fn new(
    executor: Executor,
    root_subject_types: Vec<TypeId>,
    tasks: Tasks,
    types: Types,
    intrinsics: Intrinsics,
    build_root: PathBuf,
    ignore_patterns: Vec<String>,
    use_gitignore: bool,
    local_store_dir: PathBuf,
    local_execution_root_dir: PathBuf,
    named_caches_dir: PathBuf,
    remoting_opts: RemotingOptions,
    exec_strategy_opts: ExecutionStrategyOptions,
  ) -> Result<Core, String> {
    // Randomize CAS address order to avoid thundering herds from common config.
    let mut remote_store_servers = remoting_opts.store_servers.clone();
    remote_store_servers.shuffle(&mut rand::thread_rng());

    // We re-use these certs for both the execution and store service; they're generally tied together.
    let root_ca_certs = if let Some(ref path) = remoting_opts.root_ca_certs_path {
      Some(
        std::fs::read(path)
          .map_err(|err| format!("Error reading root CA certs file {:?}: {}", path, err))?,
      )
    } else {
      None
    };

    // We re-use this token for both the execution and store service; they're generally tied together.
    let oauth_bearer_token = if let Some(ref path) = remoting_opts.oauth_bearer_token_path {
      Some(
        std::fs::read_to_string(path)
          .map_err(|err| format!("Error reading OAuth bearer token file {:?}: {}", path, err))
          .map(|v| v.trim_matches(|c| c == '\r' || c == '\n').to_owned())
          .and_then(|v| {
            if v.find(|c| c == '\r' || c == '\n').is_some() {
              Err("OAuth bearer token file must not contain multiple lines".to_string())
            } else {
              Ok(v)
            }
          })?,
      )
    } else {
      None
    };

    let local_store_dir2 = local_store_dir.clone();
    let store = safe_create_dir_all_ioerror(&local_store_dir)
      .map_err(|e| format!("Error making directory {:?}: {:?}", local_store_dir, e))
      .and_then(|_| {
        if !remoting_opts.execution_enable || remote_store_servers.is_empty() {
          Store::local_only(executor.clone(), local_store_dir)
        } else {
          Store::with_remote(
            executor.clone(),
            local_store_dir,
            remote_store_servers,
            remoting_opts.instance_name.clone(),
            root_ca_certs.clone(),
            oauth_bearer_token.clone(),
            remoting_opts.store_thread_count,
            remoting_opts.store_chunk_bytes,
            remoting_opts.store_chunk_upload_timeout,
            // TODO: Take a parameter
            store::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10))
              .unwrap(),
            remoting_opts.store_rpc_retries,
            remoting_opts.store_connection_limit,
          )
        }
      })
      .map_err(|e| format!("Could not initialize Store: {:?}", e))?;

    let process_execution_metadata = ProcessMetadata {
      instance_name: remoting_opts.instance_name,
      cache_key_gen_version: remoting_opts.execution_process_cache_namespace,
      platform_properties: remoting_opts.execution_extra_platform_properties,
    };

    let local_command_runner = process_execution::local::CommandRunner::new(
      store.clone(),
      executor.clone(),
      local_execution_root_dir.clone(),
      NamedCaches::new(named_caches_dir),
      exec_strategy_opts.cleanup_local_dirs,
    );

    let maybe_nailgunnable_local_command_runner: Box<dyn process_execution::CommandRunner> =
      if exec_strategy_opts.local_enable_nailgun {
        Box::new(process_execution::nailgun::CommandRunner::new(
          local_command_runner,
          process_execution_metadata.clone(),
          local_execution_root_dir,
          executor.clone(),
        ))
      } else {
        Box::new(local_command_runner)
      };

    let mut command_runner: Box<dyn process_execution::CommandRunner> =
      Box::new(BoundedCommandRunner::new(
        maybe_nailgunnable_local_command_runner,
        exec_strategy_opts.local_parallelism,
      ));

    if remoting_opts.execution_enable {
      let remote_command_runner: Box<dyn process_execution::CommandRunner> = {
        let command_runner: Box<dyn CommandRunner> = {
          Box::new(process_execution::remote::CommandRunner::new(
            // No problem unwrapping here because the global options validation
            // requires the remoting_opts.execution_server be present when
            // remoting_opts.execution_enable is set.
            &remoting_opts.execution_server.unwrap(),
            remoting_opts.store_servers.clone(),
            process_execution_metadata.clone(),
            root_ca_certs,
            oauth_bearer_token,
            remoting_opts.execution_headers,
            store.clone(),
            // TODO if we ever want to configure the remote platform to be something else we
            // need to take an option all the way down here and into the remote::CommandRunner struct.
            Platform::Linux,
            remoting_opts.execution_overall_deadline,
          )?)
        };

        Box::new(BoundedCommandRunner::new(
          command_runner,
          exec_strategy_opts.remote_parallelism,
        ))
      };
      command_runner = match exec_strategy_opts.speculation_strategy.as_ref() {
        "local_first" => Box::new(SpeculatingCommandRunner::new(
          command_runner,
          remote_command_runner,
          exec_strategy_opts.speculation_delay,
        )),
        "remote_first" => Box::new(SpeculatingCommandRunner::new(
          remote_command_runner,
          command_runner,
          exec_strategy_opts.speculation_delay,
        )),
        "none" => remote_command_runner,
        _ => unreachable!(),
      };
    }

    if exec_strategy_opts.use_local_cache {
      let process_execution_store = ShardedLmdb::new(
        local_store_dir2.join("processes"),
        5 * GIGABYTES,
        executor.clone(),
        DEFAULT_LEASE_TIME,
      )
      .map_err(|err| format!("Could not initialize store for process cache: {:?}", err))?;
      command_runner = Box::new(process_execution::cache::CommandRunner::new(
        command_runner.into(),
        process_execution_store,
        store.clone(),
        process_execution_metadata,
      ));
    }
    let graph = Arc::new(InvalidatableGraph(Graph::new()));

    let http_client = reqwest::Client::new();
    let rule_graph = RuleGraph::new(tasks.as_map(), root_subject_types);

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
}

impl Deref for InvalidatableGraph {
  type Target = Graph<NodeKey>;

  fn deref(&self) -> &Graph<NodeKey> {
    &self.0
  }
}

#[derive(Clone)]
pub struct Context {
  entry_id_and_run_token: Option<(EntryId, RunToken)>,
  pub core: Arc<Core>,
  pub session: Session,
  session_run_id: Uuid,
}

impl Context {
  pub fn new(core: Arc<Core>, session: Session) -> Context {
    // NB: See `impl NodeContext for Context` for more information on this naming.
    let session_run_id = session.run_id();
    Context {
      entry_id_and_run_token: None,
      core,
      session,
      session_run_id,
    }
  }

  ///
  /// Get the future value for the given Node implementation.
  ///
  pub async fn get<N: WrappedNode>(&self, node: N) -> Result<N::Item, Failure> {
    let node_result = self.core.graph.get(self, node.into()).await?;
    Ok(
      node_result
        .try_into()
        .unwrap_or_else(|_| panic!("A Node implementation was ambiguous.")),
    )
  }

  ///
  /// Same as for Self::get, but returns None if a cycle would be created.
  ///
  pub async fn get_weak<N: WrappedNode>(&self, node: N) -> Result<Option<N::Item>, Failure> {
    let node_result = self.core.graph.get_weak(self, node.into()).await?;
    Ok(node_result.map(|v| {
      v.try_into()
        .unwrap_or_else(|_| panic!("A Node implementation was ambiguous."))
    }))
  }
}

impl NodeContext for Context {
  type Node = NodeKey;
  // NB: The name "Session" is slightly overloaded between the graph crate and the engine: what the
  // graph crate calls a SessionId we refer to as the "run_id of the Session". See
  // `scheduler::Session` for more information.
  type SessionId = Uuid;

  ///
  /// Clones this Context for a new run of a Node. Because the Core of the context is an Arc, this
  /// is a shallow clone.
  ///
  fn clone_for(&self, entry_id: EntryId, run_token: RunToken) -> Context {
    Context {
      entry_id_and_run_token: Some((entry_id, run_token)),
      core: self.core.clone(),
      session: self.session.clone(),
      session_run_id: self.session_run_id,
    }
  }

  fn entry_id_and_run_token(&self) -> Option<(EntryId, RunToken)> {
    self.entry_id_and_run_token
  }

  fn session_id(&self) -> &Self::SessionId {
    &self.session_run_id
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
