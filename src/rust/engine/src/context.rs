
use futures_cpupool::CpuPool;

use externs::Externs;
use graph::Graph;
use tasks::Tasks;
use types::Types;


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
  pub pool: CpuPool,
}
