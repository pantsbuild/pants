// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use core::TypeId;
use externs;
use fs::{PosixFS, Snapshots, Store, safe_create_dir_all_ioerror, ResettablePool};
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
  pub snapshots: Snapshots,
  pub store: Store,
  pub vfs: PosixFS,
}

impl Core {
  pub fn new(
    root_subject_types: Vec<TypeId>,
    mut tasks: Tasks,
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
        .unwrap_or_else(
      |e| {
        panic!("Could not initialize Store directory {:?}", e)
      },
    );

    // TODO: Create the Snapshots directory, and then expose it as a singleton to python.
    //   see: https://github.com/pantsbuild/pants/issues/4397
    let snapshots = Snapshots::new(snapshots_dir).unwrap_or_else(|e| {
      panic!("Could not initialize Snapshot directory: {:?}", e);
    });
    tasks.singleton_replace(
      externs::unsafe_call(
        &types.construct_snapshots,
        &vec![
          externs::store_bytes(snapshots.snapshot_path().as_os_str().as_bytes()),
        ],
      ),
      types.snapshots.clone(),
    );
    let rule_graph = RuleGraph::new(&tasks, root_subject_types);

    Core {
      graph: Graph::new(),
      tasks: tasks,
      rule_graph: rule_graph,
      types: types,
      pool: pool.clone(),
      snapshots: snapshots,
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
  pub fn get<N: Node>(&self, node: N) -> NodeFuture<N::Output> {
    // TODO: Odd place for this... could do it periodically in the background?
    maybe_drain_handles().map(|handles| { externs::drop_handles(handles); });
    self.core.graph.get(self.entry_id, self, node)
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
