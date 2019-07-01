use boxfuture::BoxFuture;
use super::{
  CommandRunner,
  BoundedCommandRunner,
  ExecuteProcessRequest,
  FallibleExecuteProcessResult
};

pub struct SpeculatingCommandRunner {
  primary: BoundedCommandRunner,
  #[allow(dead_code)] // TODO(henry) actually use this command runner is certain cases
  secondary: Option<BoundedCommandRunner>,
}

impl SpeculatingCommandRunner {

  pub fn new(primary: BoundedCommandRunner, secondary: Option<BoundedCommandRunner>) -> SpeculatingCommandRunner {
    SpeculatingCommandRunner {
      primary: primary,
      secondary: secondary,
    }
  }
}

impl CommandRunner for SpeculatingCommandRunner {
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String> {
    // TODO(henry) implement delay timer and speculate about a second request
    self.primary.run(req)
  }
}
