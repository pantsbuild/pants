use crate::{
  CommandRunner, Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, Process,
};

use async_trait::async_trait;
use futures::future::{self, Either, FutureExt};
use log::{debug, trace};
use std::sync::Arc;
use std::time::Duration;
use tokio::time::delay_for;

#[derive(Clone)]
pub struct SpeculatingCommandRunner {
  primary: Arc<dyn CommandRunner>,
  secondary: Arc<dyn CommandRunner>,
  speculation_timeout: Duration,
}

impl SpeculatingCommandRunner {
  pub fn new(
    primary: Box<dyn CommandRunner>,
    secondary: Box<dyn CommandRunner>,
    speculation_timeout: Duration,
  ) -> SpeculatingCommandRunner {
    SpeculatingCommandRunner {
      primary: primary.into(),
      secondary: secondary.into(),
      speculation_timeout,
    }
  }

  async fn speculate(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    trace!(
      "Primary command runner queue length: {:?}",
      self.primary.num_waiters()
    );

    let secondary_request = {
      let command_runner = self.clone();
      let req = req.clone();
      let context = context.clone();
      async move {
        delay_for(self.speculation_timeout).await;

        trace!(
          "Secondary command runner queue length: {:?}",
          command_runner.secondary.num_waiters()
        );
        command_runner.secondary.run(req, context).await
      }
    };

    match future::select(self.primary.run(req, context), secondary_request.boxed()).await {
      Either::Left((Ok(s), _)) | Either::Right((Ok(s), _)) => Ok(s),
      Either::Left((Err(e), _)) => {
        debug!("primary request FAILED, aborting");
        Err(e)
      }
      Either::Right((Err(_secondary_request_err), primary_request)) => {
        debug!("secondary request FAILED, waiting for primary!");
        // We handle the case of the secondary failing specially. We only want to show
        // a failure to the user if the primary execution source fails. This maintains
        // feel between speculation on and off states.
        let primary_result = primary_request.await;
        if primary_result.is_ok() {
          debug!("primary request eventually SUCCEEDED after secondary failed");
        } else {
          debug!("primary request eventually FAILED after secondary failed");
        }
        primary_result
      }
    }
  }
}

#[async_trait]
impl CommandRunner for SpeculatingCommandRunner {
  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    match (
      self.primary.extract_compatible_request(req),
      self.secondary.extract_compatible_request(req),
    ) {
      (Some(req), _) => Some(req),
      (_, Some(req)) => Some(req),
      _ => None,
    }
  }

  async fn run(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    match (
      self.primary.extract_compatible_request(&req),
      self.secondary.extract_compatible_request(&req),
    ) {
      (Some(_), Some(_)) => self.speculate(req, context).await,
      (Some(_), None) => self.primary.run(req, context).await,
      (None, Some(_)) => self.secondary.run(req, context).await,
      (None, None) => Err(format!(
        "No compatible requests found for available platforms in {:?}",
        req
      )),
    }
  }
}
