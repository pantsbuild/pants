use boxfuture::BoxFuture;
use super::{
  CommandRunner,
  ExecuteProcessRequest,
  FallibleExecuteProcessResult
};

pub struct SpeculatingCommandRunner {
  primary: Box<dyn CommandRunner>,
  #[allow(dead_code)] // TODO(henry) actually use this command runner in certain cases
  secondary: Box<dyn CommandRunner>,
}

impl SpeculatingCommandRunner {

  pub fn new(primary: Box<dyn CommandRunner>, secondary: Box<dyn CommandRunner>) -> SpeculatingCommandRunner {
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
