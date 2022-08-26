use std::fmt;

use async_trait::async_trait;
use bollard::Docker;
use store::Store;
use workunit_store::RunningWorkunit;

use crate::{
  Context, FallibleProcessResultWithPlatform, ImmutableInputs, LocalCommandRunner, NamedCaches,
  Process, ProcessError,
};

/// `CommandRunner` executes processes using a local Docker client.
pub struct CommandRunner {
  _docker: Docker,
  store: Store,
  named_caches: NamedCaches,
  immutable_inputs: ImmutableInputs,
}

impl CommandRunner {
  pub fn new(
    store: Store,
    named_caches: NamedCaches,
    immutable_inputs: ImmutableInputs,
  ) -> Result<Self, String> {
    let docker = Docker::connect_with_local_defaults()
      .map_err(|err| format!("Failed to connect to local Docker: {err}"))?;
    Ok(CommandRunner {
      _docker: docker,
      store,
      named_caches,
      immutable_inputs,
    })
  }
}

impl LocalCommandRunner for CommandRunner {
  fn store(&self) -> &Store {
    &self.store
  }

  fn named_caches(&self) -> &NamedCaches {
    &self.named_caches
  }

  fn immutable_inputs(&self) -> &ImmutableInputs {
    &self.immutable_inputs
  }
}

impl fmt::Debug for CommandRunner {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    f.debug_struct("docker::CommandRunner")
      .finish_non_exhaustive()
  }
}

#[async_trait]
impl super::CommandRunner for CommandRunner {
  async fn run(
    &self,
    _context: Context,
    _workunit: &mut RunningWorkunit,
    _req: Process,
  ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
    todo!()
  }
}
