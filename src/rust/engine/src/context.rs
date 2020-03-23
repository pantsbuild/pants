// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std;
use std::collections::BTreeMap;
use std::convert::{Into, TryInto};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use futures::compat::Future01CompatExt;
use futures01::Future;

use crate::core::{Failure, TypeId};
use crate::handles::maybe_drop_handles;
use crate::nodes::{NodeKey, WrappedNode};
use crate::scheduler::Session;
use crate::tasks::{Rule, Tasks};
use crate::types::Types;
use boxfuture::{BoxFuture, Boxable};
use core::clone::Clone;
use fs::{safe_create_dir_all_ioerror, PosixFS};
use graph::{EntryId, Graph, NodeContext};
use process_execution::{
  self, speculate::SpeculatingCommandRunner, BoundedCommandRunner, ExecuteProcessRequestMetadata,
  PlatformConstraint,
};
use rand::seq::SliceRandom;
use reqwest;
use rule_graph::RuleGraph;
use sharded_lmdb::ShardedLmdb;
use store::Store;
use tokio::runtime::{Builder, Runtime};

const GIGABYTES: usize = 1024 * 1024 * 1024;

///
/// The core context shared (via Arc) between the Scheduler and the Context objects of
/// all running Nodes.
///
/// Over time, most usage of `ResettablePool` (which wraps use of blocking APIs) should migrate
/// to the Tokio `Runtime`. The next candidate is likely to be migrating PosixFS to tokio-fs once
/// https://github.com/tokio-rs/tokio/issues/369 is resolved.
///
pub struct Core {
  pub graph: Graph<NodeKey>,
  pub tasks: Tasks,
  pub rule_graph: RuleGraph<Rule>,
  pub types: Types,
  pub runtime: Runtime,
  pub executor: task_executor::Executor,
  store: Store,
  pub command_runner: Box<dyn process_execution::CommandRunner>,
  pub http_client: reqwest::Client,
  pub vfs: PosixFS,
  pub build_root: PathBuf,
}

impl Core {
  pub fn new(
    root_subject_types: Vec<TypeId>,
    tasks: Tasks,
    types: Types,
    build_root: PathBuf,
    ignore_patterns: &[String],
    local_store_dir: PathBuf,
    remote_execution: bool,
    remote_store_servers: Vec<String>,
    remote_execution_server: Option<String>,
    remote_execution_process_cache_namespace: Option<String>,
    remote_instance_name: Option<String>,
    remote_root_ca_certs_path: Option<PathBuf>,
    remote_oauth_bearer_token_path: Option<PathBuf>,
    remote_store_thread_count: usize,
    remote_store_chunk_bytes: usize,
    remote_store_chunk_upload_timeout: Duration,
    remote_store_rpc_retries: usize,
    remote_store_connection_limit: usize,
    remote_execution_extra_platform_properties: Vec<(String, String)>,
    process_execution_local_parallelism: usize,
    process_execution_remote_parallelism: usize,
    process_execution_cleanup_local_dirs: bool,
    process_execution_speculation_delay: Duration,
    process_execution_speculation_strategy: String,
    process_execution_use_local_cache: bool,
    remote_execution_headers: BTreeMap<String, String>,
    process_execution_local_enable_nailgun: bool,
  ) -> Result<Core, String> {
    // Randomize CAS address order to avoid thundering herds from common config.
    let mut remote_store_servers = remote_store_servers;
    remote_store_servers.shuffle(&mut rand::thread_rng());

    let runtime = Builder::new()
      // This use of Builder (rather than just Runtime::new()) is to allow us to lower the
      // max_threads setting. As of tokio `0.2.13`, the core threads default to num_cpus, and
      // the max threads default to a fixed value of 512. In practice, it appears to be slower
      // to allow 512 threads, and with the default stack size, 512 threads would use 1GB of RAM.
      .core_threads(num_cpus::get())
      .max_threads(num_cpus::get() * 4)
      .threaded_scheduler()
      .enable_all()
      .build()
      .map_err(|e| format!("Failed to start the runtime: {}", e))?;
    let executor = task_executor::Executor::new(runtime.handle().clone());
    // We re-use these certs for both the execution and store service; they're generally tied together.
    let root_ca_certs = if let Some(path) = remote_root_ca_certs_path {
      Some(
        std::fs::read(&path)
          .map_err(|err| format!("Error reading root CA certs file {:?}: {}", path, err))?,
      )
    } else {
      None
    };

    // We re-use this token for both the execution and store service; they're generally tied together.
    let oauth_bearer_token = if let Some(path) = remote_oauth_bearer_token_path {
      Some(
        std::fs::read_to_string(&path)
          .map_err(|err| format!("Error reading OAuth bearer token file {:?}: {}", path, err))?,
      )
    } else {
      None
    };

    let local_store_dir2 = local_store_dir.clone();
    let store = safe_create_dir_all_ioerror(&local_store_dir)
      .map_err(|e| format!("Error making directory {:?}: {:?}", local_store_dir, e))
      .and_then(|()| {
        if !remote_execution || remote_store_servers.is_empty() {
          Store::local_only(executor.clone(), local_store_dir)
        } else {
          Store::with_remote(
            executor.clone(),
            local_store_dir,
            remote_store_servers,
            remote_instance_name.clone(),
            root_ca_certs.clone(),
            oauth_bearer_token.clone(),
            remote_store_thread_count,
            remote_store_chunk_bytes,
            remote_store_chunk_upload_timeout,
            // TODO: Take a parameter
            store::BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10))
              .unwrap(),
            remote_store_rpc_retries,
            remote_store_connection_limit,
          )
        }
      })
      .map_err(|e| format!("Could not initialize Store: {:?}", e))?;

    let process_execution_metadata = ExecuteProcessRequestMetadata {
      instance_name: remote_instance_name,
      cache_key_gen_version: remote_execution_process_cache_namespace,
      platform_properties: remote_execution_extra_platform_properties,
    };

    let local_command_runner = process_execution::local::CommandRunner::new(
      store.clone(),
      executor.clone(),
      std::env::temp_dir(),
      process_execution_cleanup_local_dirs,
    );

    let maybe_nailgunnable_local_command_runner: Box<dyn process_execution::CommandRunner> =
      if process_execution_local_enable_nailgun {
        Box::new(process_execution::nailgun::CommandRunner::new(
          local_command_runner,
          process_execution_metadata.clone(),
          std::env::temp_dir(),
          executor.clone(),
        ))
      } else {
        Box::new(local_command_runner)
      };

    let mut command_runner: Box<dyn process_execution::CommandRunner> =
      Box::new(BoundedCommandRunner::new(
        maybe_nailgunnable_local_command_runner,
        process_execution_local_parallelism,
      ));

    if remote_execution {
      let remote_command_runner: Box<dyn process_execution::CommandRunner> =
        Box::new(BoundedCommandRunner::new(
          Box::new(process_execution::remote::CommandRunner::new(
            // No problem unwrapping here because the global options validation
            // requires the remote_execution_server be present when remote_execution is set.
            &remote_execution_server.unwrap(),
            process_execution_metadata.clone(),
            root_ca_certs,
            oauth_bearer_token,
            remote_execution_headers,
            store.clone(),
            // TODO if we ever want to configure the remote platform to be something else we
            // need to take an option all the way down here and into the remote::CommandRunner struct.
            PlatformConstraint::Linux,
            executor.clone(),
            std::time::Duration::from_secs(160),
            std::time::Duration::from_millis(500),
            std::time::Duration::from_secs(5),
          )?),
          process_execution_remote_parallelism,
        ));
      command_runner = match process_execution_speculation_strategy.as_ref() {
        "local_first" => Box::new(SpeculatingCommandRunner::new(
          command_runner,
          remote_command_runner,
          process_execution_speculation_delay,
        )),
        "remote_first" => Box::new(SpeculatingCommandRunner::new(
          remote_command_runner,
          command_runner,
          process_execution_speculation_delay,
        )),
        "none" => remote_command_runner,
        _ => unreachable!(),
      };
    }

    if process_execution_use_local_cache {
      let process_execution_store = ShardedLmdb::new(
        local_store_dir2.join("processes"),
        5 * GIGABYTES,
        executor.clone(),
      )
      .map_err(|err| format!("Could not initialize store for process cache: {:?}", err))?;
      command_runner = Box::new(process_execution::cache::CommandRunner {
        underlying: command_runner.into(),
        process_execution_store,
        file_store: store.clone(),
        metadata: process_execution_metadata,
      })
    }

    let http_client = reqwest::Client::new();
    let rule_graph = RuleGraph::new(tasks.as_map(), root_subject_types);

    Ok(Core {
      graph: Graph::new(),
      tasks: tasks,
      rule_graph: rule_graph,
      types: types,
      runtime,
      executor: executor.clone(),
      store,
      command_runner,
      http_client,
      // TODO: Errors in initialization should definitely be exposed as python
      // exceptions, rather than as panics.
      vfs: PosixFS::new(&build_root, &ignore_patterns, executor)
        .map_err(|e| format!("Could not initialize VFS: {:?}", e))?,
      build_root: build_root,
    })
  }

  pub fn store(&self) -> Store {
    self.store.clone()
  }
}

#[derive(Clone)]
pub struct Context {
  entry_id: Option<EntryId>,
  pub core: Arc<Core>,
  pub session: Session,
}

impl Context {
  pub fn new(core: Arc<Core>, session: Session) -> Context {
    Context {
      entry_id: None,
      core,
      session,
    }
  }

  ///
  /// Get the future value for the given Node implementation.
  ///
  pub fn get<N: WrappedNode>(&self, node: N) -> BoxFuture<N::Item, Failure> {
    // TODO: Odd place for this... could do it periodically in the background?
    maybe_drop_handles();
    let result = if let Some(entry_id) = self.entry_id {
      self.core.graph.get(entry_id, self, node.into()).to_boxed()
    } else {
      self.core.graph.create(node.into(), self).to_boxed()
    };
    result
      .map(|node_result| {
        node_result
          .try_into()
          .unwrap_or_else(|_| panic!("A Node implementation was ambiguous."))
      })
      .to_boxed()
  }
}

impl NodeContext for Context {
  type Node = NodeKey;
  type SessionId = String;

  ///
  /// Clones this Context for a new EntryId. Because the Core of the context is an Arc, this
  /// is a shallow clone.
  ///
  fn clone_for(&self, entry_id: EntryId) -> Context {
    Context {
      entry_id: Some(entry_id),
      core: self.core.clone(),
      session: self.session.clone(),
    }
  }

  fn session_id(&self) -> &Self::SessionId {
    self.session.build_id()
  }

  fn graph(&self) -> &Graph<NodeKey> {
    &self.core.graph
  }

  fn spawn<F>(&self, future: F)
  where
    F: Future<Item = (), Error = ()> + Send + 'static,
  {
    self.core.executor.spawn_and_ignore(async move {
      let _ = future.compat().await;
    });
  }
}
