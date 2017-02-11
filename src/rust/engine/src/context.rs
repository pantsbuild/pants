
use std::sync::{RwLock, RwLockReadGuard};

use futures_cpupool::{self, CpuPool};

use externs::Externs;
use graph::Graph;
use tasks::Tasks;
use types::Types;
use fs::Snapshots;


/**
 * The core context shared (via Arc) between the Scheduler and the Context objects of
 * all running Nodes.
 *
 * TODO: Move `nodes.Context` to this module.
 */
pub struct Core {
  pub graph: Graph,
  pub tasks: Tasks,
  pub types: Types,
  pub externs: Externs,
  pub snapshots: Snapshots,
  // The pool needs to be reinitialized after a fork, so it is protected by a lock.
  pool: RwLock<CpuPool>,
}

impl Core {
  pub fn new(tasks: Tasks, types: Types, externs: Externs) -> Core {
    Core {
      graph: Graph::new(),
      tasks: tasks,
      types: types,
      externs: externs,
      snapshots: Snapshots::new()
        .unwrap_or_else(|e| {
          panic!("Could not initialize Snapshot directory: {:?}", e);
        }),
      pool: RwLock::new(Core::create_pool()),
    }
  }

  fn create_pool() -> CpuPool {
    futures_cpupool::Builder::new()
      .name_prefix("engine-")
      .create()
  }

  pub fn pool(&self) -> RwLockReadGuard<CpuPool> {
    self.pool.read().unwrap()
  }

  /**
   * Reinitializes a Core in a new process (basically, recreates its CpuPool).
   */
  pub fn post_fork(&self) {
    let mut pool = self.pool.write().unwrap();
    *pool = Core::create_pool();
  }
}
