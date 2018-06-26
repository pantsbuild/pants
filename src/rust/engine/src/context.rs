// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use tokio::runtime::Runtime;

use futures::Future;

use boxfuture::{BoxFuture, Boxable};
use core::{Failure, TypeId};
use externs;
use fs::{safe_create_dir_all_ioerror, PosixFS, ResettablePool, Store};
use graph::{EntryId, Graph, NodeContext};
use handles::maybe_drain_handles;
use nodes::{NodeKey, TryInto, WrappedNode};
use process_execution::{self, BoundedCommandRunner, CommandRunner};
use resettable::Resettable;
use rule_graph::RuleGraph;
use tasks::Tasks;
use types::Types;

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
  pub rule_graph: RuleGraph,
  pub types: Types,
  pub fs_pool: Arc<ResettablePool>,
  pub runtime: Resettable<Arc<Runtime>>,
  pub store: Store,
  pub vfs: PosixFS,
  pub command_runner: BoundedCommandRunner,
}

impl Core {
  pub fn new(
    root_subject_types: Vec<TypeId>,
    tasks: Tasks,
    types: Types,
    build_root: &Path,
    ignore_patterns: Vec<String>,
    work_dir: &Path,
    remote_store_server: Option<String>,
    remote_execution_server: Option<String>,
    remote_store_thread_count: usize,
    remote_store_chunk_bytes: usize,
    remote_store_chunk_upload_timeout: Duration,
    process_execution_parallelism: usize,
    process_execution_cleanup_local_dirs: bool,
  ) -> Core {
    let mut snapshots_dir = PathBuf::from(work_dir);
    snapshots_dir.push("snapshots");

    let fs_pool = Arc::new(ResettablePool::new("io-".to_string()));
    let runtime = Resettable::new(|| {
      Arc::new(Runtime::new().unwrap_or_else(|e| panic!("Could not initialize Runtime: {:?}", e)))
    });

    let store_path = match std::env::home_dir() {
      Some(home_dir) => home_dir.join(".cache").join("pants").join("lmdb_store"),
      None => panic!("Could not find home dir"),
    };

    let store = safe_create_dir_all_ioerror(&store_path)
      .map_err(|e| format!("Error making directory {:?}: {:?}", store_path, e))
      .and_then(|()| match remote_store_server {
        Some(address) => Store::with_remote(
          store_path,
          fs_pool.clone(),
          address,
          remote_store_thread_count,
          remote_store_chunk_bytes,
          remote_store_chunk_upload_timeout,
        ),
        None => Store::local_only(store_path, fs_pool.clone()),
      })
      .unwrap_or_else(|e| panic!("Could not initialize Store: {:?}", e));

    let underlying_command_runner: Box<process_execution::CommandRunner> =
      match remote_execution_server {
        Some(address) => Box::new(process_execution::remote::CommandRunner::new(
          address,
          // Allow for some overhead for bookkeeping threads (if any).
          process_execution_parallelism + 2,
          store.clone(),
        )),
        None => Box::new(process_execution::local::CommandRunner::new(
          store.clone(),
          fs_pool.clone(),
          work_dir.to_path_buf(),
          process_execution_cleanup_local_dirs,
        )),
      };

    let command_runner =
      BoundedCommandRunner::new(underlying_command_runner, process_execution_parallelism);

    let rule_graph = RuleGraph::new(&tasks, root_subject_types);

    Core {
      graph: Graph::new(),
      tasks: tasks,
      rule_graph: rule_graph,
      types: types,
      fs_pool: fs_pool.clone(),
      runtime: runtime,
      store: store,
      // FIXME: Errors in initialization should definitely be exposed as python
      // exceptions, rather than as panics.
      vfs: PosixFS::new(build_root, fs_pool, ignore_patterns).unwrap_or_else(|e| {
        panic!("Could not initialize VFS: {:?}", e);
      }),
      command_runner: command_runner,
    }
  }

  pub fn pre_fork(&self) {
    self.fs_pool.reset();
    self.store.reset_prefork();
    self.runtime.reset();
    self.command_runner.reset_prefork();
  }
}

#[derive(Clone)]
pub struct Context {
  pub entry_id: EntryId,
  pub core: Arc<Core>,
}

impl Context {
  pub fn new(entry_id: EntryId, core: Arc<Core>) -> Context {
    Context {
      entry_id: entry_id,
      core: core,
    }
  }

  ///
  /// Get the future value for the given Node implementation.
  ///
  pub fn get<N: WrappedNode>(&self, node: N) -> BoxFuture<N::Item, Failure> {
    // TODO: Odd place for this... could do it periodically in the background?
    if let Some(handles) = maybe_drain_handles() {
      externs::drop_handles(&handles);
    }
    self
      .core
      .graph
      .get(self.entry_id, self, node.into())
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

  ///
  /// Clones this Context for a new EntryId. Because the Core of the context is an Arc, this
  /// is a shallow clone.
  ///
  fn clone_for(&self, entry_id: EntryId) -> Context {
    Context {
      entry_id: entry_id,
      core: self.core.clone(),
    }
  }

  fn graph(&self) -> &Graph<NodeKey> {
    &self.core.graph
  }
}
