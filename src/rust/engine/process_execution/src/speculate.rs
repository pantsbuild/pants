use crate::{
  CommandRunner, Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, Process,
};
use boxfuture::{BoxFuture, Boxable};
use futures::future::{FutureExt, TryFutureExt};
use futures01::future::{err, ok, Either, Future};
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
      speculation_timeout: speculation_timeout,
    }
  }

  fn speculate(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> BoxFuture<FallibleProcessResultWithPlatform, String> {
    let delay = delay_for(self.speculation_timeout)
      .unit_error()
      .boxed()
      .compat();
    let req2 = req.clone();
    trace!(
      "Primary command runner queue length: {:?}",
      self.primary.num_waiters()
    );
    self
      .primary
      .run(req, context.clone())
      .select2({
        let command_runner = self.clone();
        delay.then(move |_| {
          trace!(
            "Secondary command runner queue length: {:?}",
            command_runner.secondary.num_waiters()
          );
          command_runner.secondary.run(req2, context)
        })
      })
      .then(|raced_result| match raced_result {
        Ok(either_success) => {
          // .split() takes out the homogeneous success type for either primary or
          // secondary successes.
          ok::<FallibleProcessResultWithPlatform, String>(either_success.split().0).to_boxed()
        }
        Err(Either::A((failed_primary_res, _))) => {
          debug!("primary request FAILED, aborting");
          err::<FallibleProcessResultWithPlatform, String>(failed_primary_res).to_boxed()
        }
        // We handle the case of the secondary failing specially. We only want to show
        // a failure to the user if the primary execution source fails. This maintains
        // feel between speculation on and off states.
        Err(Either::B((_failed_secondary_res, outstanding_primary_request))) => {
          debug!("secondary request FAILED, waiting for primary!");
          outstanding_primary_request
            .then(|primary_result| {
              if primary_result.is_ok() {
                debug!("primary request eventually SUCCEEDED after secondary failed");
              } else {
                debug!("primary request eventually FAILED after secondary failed");
              }
              primary_result
            })
            .to_boxed()
        }
      })
      .to_boxed()
  }
}

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

  fn run(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> BoxFuture<FallibleProcessResultWithPlatform, String> {
    match (
      self.primary.extract_compatible_request(&req),
      self.secondary.extract_compatible_request(&req),
    ) {
      (Some(_), Some(_)) => self.speculate(req, context),
      (Some(_), None) => self.primary.run(req, context),
      (None, Some(_)) => self.secondary.run(req, context),
      (None, None) => err(format!(
        "No compatible requests found for available platforms in {:?}",
        req
      ))
      .to_boxed(),
    }
  }
}
