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
use crate::scheduler::Session;
use crate::tasks::{Rule, Tasks};
use crate::types::Types;

use fs::{safe_create_dir_all_ioerror, GitignoreStyleExcludes, PosixFS};
use graph::{self, EntryId, Graph, InvalidationResult, NodeContext};
use log::info;
use parking_lot::Mutex;
use process_execution::{
  self, speculate::SpeculatingCommandRunner, BoundedCommandRunner, CommandRunner, NamedCaches,
  Platform, ProcessMetadata,
};
use rand::seq::SliceRandom;
use regex::Regex;
use rule_graph::RuleGraph;
use sharded_lmdb::{ShardedLmdb, DEFAULT_LEASE_TIME};
use store::Store;
use task_executor::Executor;
use uuid::Uuid;
use watch::{Invalidatable, InvalidationWatcher};

const GIGABYTES: usize = 1024 * 1024 * 1024;

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
  fn make_store(
    executor: &Executor,
    local_store_dir: &Path,
    enable_remote: bool,
    remoting_opts: &RemotingOptions,
    remote_store_servers: &[String],
    root_ca_certs: &Option<Vec<u8>>,
    oauth_bearer_token: &Option<String>,
  ) -> Result<Store, String> {
    if enable_remote {
      Store::with_remote(
        executor.clone(),
        local_store_dir,
        remote_store_servers.to_vec(),
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
    } else {
      Store::local_only(executor.clone(), local_store_dir.to_path_buf())
    }
  }

  fn make_local_execution_runner(
    store: &Store,
    executor: &Executor,
    local_execution_root_dir: &Path,
    named_caches_dir: &Path,
    process_execution_metadata: &ProcessMetadata,
    exec_strategy_opts: &ExecutionStrategyOptions,
  ) -> Result<Box<dyn CommandRunner>, String> {
    let local_command_runner = process_execution::local::CommandRunner::new(
      store.clone(),
      executor.clone(),
      local_execution_root_dir.to_path_buf(),
      NamedCaches::new(named_caches_dir.to_path_buf()),
      exec_strategy_opts.cleanup_local_dirs,
    );

    let maybe_nailgunnable_local_command_runner: Box<dyn process_execution::CommandRunner> =
      if exec_strategy_opts.local_enable_nailgun {
        Box::new(process_execution::nailgun::CommandRunner::new(
          local_command_runner,
          process_execution_metadata.clone(),
          local_execution_root_dir.to_path_buf(),
          executor.clone(),
        ))
      } else {
        Box::new(local_command_runner)
      };

    Ok(Box::new(BoundedCommandRunner::new(
      maybe_nailgunnable_local_command_runner,
      exec_strategy_opts.local_parallelism,
    )))
  }

  fn make_remote_execution_runner(
    store: &Store,
    process_execution_metadata: &ProcessMetadata,
    remoting_opts: &RemotingOptions,
    root_ca_certs: &Option<Vec<u8>>,
    oauth_bearer_token: &Option<String>,
  ) -> Result<Box<dyn CommandRunner>, String> {
    Ok(Box::new(process_execution::remote::CommandRunner::new(
      // No problem unwrapping here because the global options validation
      // requires the remoting_opts.execution_server be present when
      // remoting_opts.execution_enable is set.
      &remoting_opts.execution_server.clone().unwrap(),
      remoting_opts.store_servers.clone(),
      process_execution_metadata.clone(),
      root_ca_certs.clone(),
      oauth_bearer_token.clone(),
      remoting_opts.execution_headers.clone(),
      store.clone(),
      // TODO if we ever want to configure the remote platform to be something else we
      // need to take an option all the way down here and into the remote::CommandRunner struct.
      Platform::Linux,
      remoting_opts.execution_overall_deadline,
      Duration::from_millis(100),
    )?))
  }

  fn make_command_runner(
    store: &Store,
    executor: &Executor,
    local_execution_root_dir: &Path,
    named_caches_dir: &Path,
    local_store_dir: &Path,
    process_execution_metadata: &ProcessMetadata,
    root_ca_certs: &Option<Vec<u8>>,
    oauth_bearer_token: &Option<String>,
    exec_strategy_opts: &ExecutionStrategyOptions,
    remoting_opts: &RemotingOptions,
  ) -> Result<Box<dyn CommandRunner>, String> {
    let local_command_runner = Core::make_local_execution_runner(
      store,
      executor,
      local_execution_root_dir,
      named_caches_dir,
      process_execution_metadata,
      &exec_strategy_opts,
    )?;

    let command_runner: Box<dyn CommandRunner> = if remoting_opts.execution_enable {
      let remote_command_runner: Box<dyn process_execution::CommandRunner> = {
        Box::new(BoundedCommandRunner::new(
          Core::make_remote_execution_runner(
            store,
            process_execution_metadata,
            &remoting_opts,
            root_ca_certs,
            oauth_bearer_token,
          )?,
          exec_strategy_opts.remote_parallelism,
        ))
      };

      match exec_strategy_opts.speculation_strategy.as_ref() {
        "local_first" => Box::new(SpeculatingCommandRunner::new(
          local_command_runner,
          remote_command_runner,
          exec_strategy_opts.speculation_delay,
        )),
        "remote_first" => Box::new(SpeculatingCommandRunner::new(
          remote_command_runner,
          local_command_runner,
          exec_strategy_opts.speculation_delay,
        )),
        "none" => remote_command_runner,
        _ => unreachable!(),
      }
    } else {
      local_command_runner
    };

    let maybe_cached_command_runner = if exec_strategy_opts.use_local_cache {
      let process_execution_store = ShardedLmdb::new(
        local_store_dir.join("processes"),
        5 * GIGABYTES,
        executor.clone(),
        DEFAULT_LEASE_TIME,
      )
      .map_err(|err| format!("Could not initialize store for process cache: {:?}", err))?;
      Box::new(process_execution::cache::CommandRunner::new(
        command_runner.into(),
        process_execution_store,
        store.clone(),
        process_execution_metadata.clone(),
      ))
    } else {
      command_runner
    };

    Ok(maybe_cached_command_runner)
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
    local_store_dir: PathBuf,
    local_execution_root_dir: PathBuf,
    named_caches_dir: PathBuf,
    ca_certs_path: Option<PathBuf>,
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

    let store = safe_create_dir_all_ioerror(&local_store_dir)
      .map_err(|e| format!("Error making directory {:?}: {:?}", local_store_dir, e))
      .and_then(|_| {
        Core::make_store(
          &executor,
          &local_store_dir,
          remoting_opts.execution_enable && !remote_store_servers.is_empty(),
          &remoting_opts,
          &remote_store_servers,
          &root_ca_certs,
          &oauth_bearer_token,
        )
      })
      .map_err(|e| format!("Could not initialize Store: {:?}", e))?;

    let process_execution_metadata = ProcessMetadata {
      instance_name: remoting_opts.instance_name.clone(),
      cache_key_gen_version: remoting_opts.execution_process_cache_namespace.clone(),
      platform_properties: remoting_opts.execution_extra_platform_properties.clone(),
    };

    let command_runner = Core::make_command_runner(
      &store,
      &executor,
      &local_execution_root_dir,
      &named_caches_dir,
      &local_store_dir,
      &process_execution_metadata,
      &root_ca_certs,
      &oauth_bearer_token,
      &exec_strategy_opts,
      &remoting_opts,
    )?;

    let graph = Arc::new(InvalidatableGraph(Graph::new()));

    // These certs are for downloads, not to be confused with the ones used for remoting.
    let ca_certs = Core::load_certificates(ca_certs_path)?;

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
