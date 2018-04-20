// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Weak};

use core::TypeId;
use externs;
use fs::{safe_create_dir_all_ioerror, PosixFS, ResettablePool, Store};
use graph::{EntryId, Graph};
use handles::maybe_drain_handles;
use nodes::{Node, NodeFuture};
use rule_graph::RuleGraph;
use tasks::Tasks;
use types::Types;

///
/// The core context shared (via Arc) between the Scheduler and the Context objects of
/// all running Nodes.
///
pub struct Core {
  pub graph: Graph,
  pub tasks: Tasks,
  pub rule_graph: RuleGraph,
  pub types: Types,
  pub pool: Arc<ResettablePool>,
  pub store: Store,
  pub vfs: PosixFS,
}

impl Core {
  pub fn new(
    root_subject_types: Vec<TypeId>,
    tasks: Tasks,
    types: Types,
    build_root: &Path,
    ignore_patterns: Vec<String>,
    work_dir: &Path,
  ) -> Core {
    let mut snapshots_dir = PathBuf::from(work_dir);
    snapshots_dir.push("snapshots");

    let pool = Arc::new(ResettablePool::new("io-".to_string()));

    let store_path = match std::env::home_dir() {
      Some(home_dir) => home_dir.join(".cache").join("pants").join("lmdb_store"),
      None => panic!("Could not find home dir"),
    };

    let store = safe_create_dir_all_ioerror(&store_path)
      .map_err(|e| format!("{:?}", e))
      .and_then(|()| Store::local_only(store_path, pool.clone()))
      .unwrap_or_else(|e| panic!("Could not initialize Store directory {:?}", e));

    let rule_graph = RuleGraph::new(&tasks, root_subject_types);

    Core {
      graph: Graph::new(),
      tasks: tasks,
      rule_graph: rule_graph,
      types: types,
      pool: pool.clone(),
      store: store,
      // FIXME: Errors in initialization should definitely be exposed as python
      // exceptions, rather than as panics.
      vfs: PosixFS::new(build_root, pool, ignore_patterns).unwrap_or_else(|e| {
        panic!("Could not initialize VFS: {:?}", e);
      }),
    }
  }

  pub fn pre_fork(&self) {
    self.pool.reset();
    self.store.reset_lmdb_connections();
  }
}

#[derive(Clone)]
pub struct Context {
  pub entry_id: EntryId,
  pub core: Weak<Core>,
}

impl Context {
  pub fn new(entry_id: EntryId, core: Weak<Core>) -> Context {
    Context {
      entry_id: entry_id,
      core: core,
    }
  }

  pub fn core(&self) -> Arc<Core> {
    // The effect of this is that when a `Scheduler` is dropped, the only strong reference to the
    // `Core` will also be dropped, and any un-run `Nodes` will become un-runnable. I believe that
    // panic'ing in this situation is reasonable, because without a `Scheduler` reference, it is
    // impossible to actually access the `Nodes`.
    self
      .core
      .upgrade()
      .expect("The Core of the Scheduler that this Node was created for has been dropped.")
  }

  ///
  /// Get the future value for the given Node implementation.
  ///
  pub fn get<N: Node>(&self, node: N) -> NodeFuture<N::Output> {
    // TODO: Odd place for this... could do it periodically in the background?
    maybe_drain_handles().map(|handles| {
      externs::drop_handles(handles);
    });
    self.core().graph.get(self.entry_id, self, node)
  }
}

pub trait ContextFactory {
  fn create(&self, entry_id: EntryId) -> Context;
}

impl ContextFactory for Context {
  ///
  /// Clones this Context for a new EntryId. Because the Core of the context is an Arc, this
  /// is a shallow clone.
  ///
  fn create(&self, entry_id: EntryId) -> Context {
    Context {
      entry_id: entry_id,
      core: self.core.clone(),
    }
  }
}
