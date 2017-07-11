// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::os::unix::ffi::OsStrExt;
use std::path::PathBuf;
use std::sync::Arc;

use core::TypeId;
use externs;
use fs::{PosixFS, Snapshots};
use graph::{EntryId, Graph};
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
  pub snapshots: Snapshots,
  pub vfs: PosixFS,
}

impl Core {
  pub fn new(
    root_subject_types: Vec<TypeId>,
    mut tasks: Tasks,
    types: Types,
    build_root: PathBuf,
    ignore_patterns: Vec<String>,
    work_dir: PathBuf,
  ) -> Core {
    let mut snapshots_dir = work_dir.clone();
    snapshots_dir.push("snapshots");

    // TODO: Create the Snapshots directory, and then expose it as a singleton to python.
    //   see: https://github.com/pantsbuild/pants/issues/4397
    let snapshots =
      Snapshots::new(snapshots_dir)
        .unwrap_or_else(|e| {
          panic!("Could not initialize Snapshot directory: {:?}", e);
        });
    tasks.singleton_replace(
      externs::invoke_unsafe(
        &types.construct_snapshots,
        &vec![externs::store_bytes(snapshots.snapshot_path().as_os_str().as_bytes())],
      ),
      types.snapshots.clone(),
    );
    let rule_graph = RuleGraph::new(&tasks, root_subject_types);

    Core {
      graph: Graph::new(),
      tasks: tasks,
      types: types,
      rule_graph: rule_graph,
      snapshots: snapshots,
      // FIXME: Errors in initialization should definitely be exposed as python
      // exceptions, rather than as panics.
      vfs:
        PosixFS::new(build_root, ignore_patterns)
        .unwrap_or_else(|e| {
          panic!("Could not initialize VFS: {:?}", e);
        }),
    }
  }

  pub fn pre_fork(&self) {
    self.vfs.pre_fork();
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
