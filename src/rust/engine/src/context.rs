// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::os::unix::ffi::OsStrExt;
use std::path::PathBuf;
use std::sync::{Arc, RwLock, RwLockReadGuard};

use futures_cpupool::{self, CpuPool};

use externs;
use fs::{PosixFS, Snapshots};
use graph::{EntryId, Graph};
use tasks::Tasks;
use types::Types;


/**
 * The core context shared (via Arc) between the Scheduler and the Context objects of
 * all running Nodes.
 */
pub struct Core {
  pub graph: Graph,
  pub tasks: Tasks,
  pub types: Types,
  pub snapshots: Snapshots,
  pub vfs: PosixFS,
  // TODO: This is a second pool (relative to the VFS pool), upon which all work is
  // submitted. See https://github.com/pantsbuild/pants/issues/4298
  pool: RwLock<Option<CpuPool>>,
}

impl Core {
  pub fn new(
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
    Core {
      graph: Graph::new(),
      tasks: tasks,
      types: types,
      snapshots: snapshots,
      // FIXME: Errors in initialization should definitely be exposed as python
      // exceptions, rather than as panics.
      vfs:
        PosixFS::new(build_root, ignore_patterns)
        .unwrap_or_else(|e| {
          panic!("Could not initialize VFS: {:?}", e);
        }),
      pool: RwLock::new(Some(Core::create_pool())),
    }
  }

  pub fn pool(&self) -> RwLockReadGuard<Option<CpuPool>> {
    self.pool.read().unwrap()
  }

  fn create_pool() -> CpuPool {
    futures_cpupool::Builder::new()
      .name_prefix("engine-")
      .create()
  }

  pub fn pre_fork(&self) {
    let mut pool = self.pool.write().unwrap();
    *pool = None;
  }

  /**
   * Reinitializes a Core in a new process (basically, recreates its CpuPool).
   */
  pub fn post_fork(&self) {
    // Reinitialize the VFS pool.
    self.vfs.post_fork();
    // And our own.
    let mut pool = self.pool.write().unwrap();
    *pool = Some(Core::create_pool());
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
  fn pool(&self) -> RwLockReadGuard<Option<CpuPool>>;
}

impl ContextFactory for Context {
  /**
   * Clones this Context for a new EntryId. Because the Core of the context is an Arc, this
   * is a shallow clone.
   */
  fn create(&self, entry_id: EntryId) -> Context {
    Context {
      entry_id: entry_id,
      core: self.core.clone(),
    }
  }

  fn pool(&self) -> RwLockReadGuard<Option<CpuPool>> {
    self.core.pool()
  }
}
