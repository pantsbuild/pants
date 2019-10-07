use crate::{
  CommandRunner, Context, ExecuteProcessRequest, FallibleExecuteProcessResult,
  MultiPlatformExecuteProcessRequest,
};
use boxfuture::{BoxFuture, Boxable};
use futures::future::{err, ok, Either, Future};
use log::{debug, warn};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio_timer::Delay;

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
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    debug!("request is compatible with both platforms...speculating");
    let delay = Delay::new(Instant::now() + self.speculation_timeout);
    let req2 = req.clone();
    let workunit_store2 = workunit_store.clone();
    debug!(
      "Running primary command. Num waiters is {:?}",
      self.primary.num_waiters()
    );
    self
      .primary
      .run(req, workunit_store)
      .select2({
        let command_runner = self.clone();
        delay.then(move |_| {
          warn!(
            "delay finished, running second command, num waiters are {:?}",
            command_runner.secondary.num_waiters()
          );
          command_runner.secondary.run(req2, workunit_store2)
        })
      })
      .then(|raced_result| match raced_result {
        Ok(either_success) => {
          // split take out the homogeneous success type for either primary or
          // sec"ondary successes.
          ok::<FallibleExecuteProcessResult, String>(either_success.split().0).to_boxed()
        }
        Err(Either::A((failed_primary_res, _))) => {
          debug!("primary request FAILED, aborting");
          err::<FallibleExecuteProcessResult, String>(failed_primary_res).to_boxed()
        }
        // We handle the case of the secondary failing specially. We only want to show
        // a failure to the user if the primary execution source fails. This maintains
        // feel between speculation on and off states.
        Err(Either::B((_failed_secondary_res, outstanding_primary_request))) => {
          warn!("secondary request FAILED, waiting for primary!");
          outstanding_primary_request
            .then(|primary_result| match primary_result {
              Ok(primary_success) => {
                warn!("primary request eventually SUCCEEDED after secondary failed");
                ok::<FallibleExecuteProcessResult, String>(primary_success).to_boxed()
              }
              Err(primary_failure) => {
                debug!("primary request eventually FAILED after secondary failed");
                err::<FallibleExecuteProcessResult, String>(primary_failure).to_boxed()
              }
            })
            .to_boxed()
        }
      })
      .to_boxed()
  }
}

impl CommandRunner for SpeculatingCommandRunner {
  fn extract_compatible_request(
    &self,
    req: &MultiPlatformExecuteProcessRequest,
  ) -> Option<ExecuteProcessRequest> {
    match (
      self.primary.extract_compatible_request(req),
      self.secondary.extract_compatible_request(req),
    ) {
      (Some(req), _) => Some(req.clone()),
      (_, Some(req)) => Some(req.clone()),
      _ => None,
    }
  }

  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
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

#[cfg(test)]
mod tests {
  use crate::remote::tests::echo_foo_request;
  use boxfuture::{BoxFuture, Boxable};
  use bytes::Bytes;
  use futures::future::Future;
  use hashing::EMPTY_DIGEST;
  use std::sync::{Arc, Mutex};
  use std::time::{Duration, Instant};
  use tokio;
  use tokio_timer::Delay;

  use super::{
    CommandRunner, Context, ExecuteProcessRequest, FallibleExecuteProcessResult,
    MultiPlatformExecuteProcessRequest, SpeculatingCommandRunner,
  };
  use crate::Platform;

  #[test]
  fn test_no_speculation() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(0, 0, 100, false, false, true, true);
    assert_eq![1, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m1")];
  }

  #[test]
  fn test_speculate() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(100, 0, 10, false, false, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m2")]
  }

  #[test]
  fn first_req_slow_success() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(500, 1000, 250, false, false, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m1")]
  }

  #[test]
  fn first_req_slow_fail() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(1000, 0, 100, true, false, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m2")]
  }

  #[test]
  fn first_req_fast_fail() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(500, 1000, 250, true, false, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap_err(), Bytes::from("m1")]
  }

  #[test]
  fn only_fail_on_primary_result() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(1000, 0, 100, true, true, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![2, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap_err(), Bytes::from("m1")]
  }

  #[test]
  fn platform_compatible_with_1st_runs_once() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(0, 0, 100, false, false, true, false);
    assert_eq![1, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m1")]
  }

  #[test]
  fn platform_compatible_with_2nd_runs_once() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(0, 0, 100, false, false, false, true);
    assert_eq![1, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m2")]
  }

  #[test]
  fn platform_compatible_with_both_speculates() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(1000, 1000, 500, false, false, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m1")]
  }

  fn run_speculation_test(
    r1_latency_ms: u64,
    r2_latency_ms: u64,
    speculation_delay_ms: u64,
    r1_is_err: bool,
    r2_is_err: bool,
    r1_is_compatible: bool,
    r2_is_compatible: bool,
  ) -> (
    Result<FallibleExecuteProcessResult, String>,
    Arc<Mutex<u32>>,
    Arc<Mutex<u32>>,
  ) {
    let runtime = tokio::runtime::Runtime::new().unwrap();
    let execute_request = echo_foo_request();
    let msg1: String = "m1".into();
    let msg2: String = "m2".into();
    let context = Context::default();
    let call_counter = Arc::new(Mutex::new(0));
    let finished_counter = Arc::new(Mutex::new(0));
    let runner = SpeculatingCommandRunner::new(
      Box::new(make_delayed_command_runner(
        msg1.clone(),
        r1_latency_ms,
        r1_is_err,
        r1_is_compatible,
        call_counter.clone(),
        finished_counter.clone(),
      )),
      Box::new(make_delayed_command_runner(
        msg2.clone(),
        r2_latency_ms,
        r2_is_err,
        r2_is_compatible,
        call_counter.clone(),
        finished_counter.clone(),
      )),
      Duration::from_millis(speculation_delay_ms),
    );
    (
      runtime.block_on_all(runner.run(execute_request, context)),
      call_counter,
      finished_counter,
    )
  }

  fn make_delayed_command_runner(
    msg: String,
    delay: u64,
    is_err: bool,
    is_compatible: bool,
    call_counter: Arc<Mutex<u32>>,
    finished_counter: Arc<Mutex<u32>>,
  ) -> DelayedCommandRunner {
    let result = if is_err {
      Err(msg.into())
    } else {
      Ok(FallibleExecuteProcessResult {
        stdout: msg.into(),
        stderr: "".into(),
        exit_code: 0,
        output_directory: EMPTY_DIGEST,
        execution_attempts: vec![],
      })
    };
    DelayedCommandRunner::new(
      Duration::from_millis(delay),
      result,
      is_compatible,
      call_counter,
      finished_counter,
    )
  }

  #[derive(Clone)]
  struct DelayedCommandRunner {
    delay: Duration,
    result: Result<FallibleExecuteProcessResult, String>,
    is_compatible: bool,
    call_counter: Arc<Mutex<u32>>,
    finished_counter: Arc<Mutex<u32>>,
  }

  impl DelayedCommandRunner {
    pub fn new(
      delay: Duration,
      result: Result<FallibleExecuteProcessResult, String>,
      is_compatible: bool,
      call_counter: Arc<Mutex<u32>>,
      finished_counter: Arc<Mutex<u32>>,
    ) -> DelayedCommandRunner {
      DelayedCommandRunner {
        delay,
        result,
        is_compatible,
        call_counter,
        finished_counter,
      }
    }
    fn incr_call_counter(&self) {
      let mut calls = self.call_counter.lock().unwrap();
      *calls += 1;
    }
    fn incr_finished_counter(&self) {
      let mut calls = self.finished_counter.lock().unwrap();
      *calls += 1;
    }
  }

  impl CommandRunner for DelayedCommandRunner {
    fn run(
      &self,
      _req: MultiPlatformExecuteProcessRequest,
      _context: Context,
    ) -> BoxFuture<FallibleExecuteProcessResult, String> {
      let delay = Delay::new(Instant::now() + self.delay);
      let exec_result = self.result.clone();
      let command_runner = self.clone();
      command_runner.incr_call_counter();
      delay
        .then(move |delay_res| match delay_res {
          Ok(_) => exec_result,
          Err(_) => Err(String::from("Timer failed during testing")),
        })
        .then(move |res| {
          command_runner.incr_finished_counter();
          res
        })
        .to_boxed()
    }

    fn extract_compatible_request(
      &self,
      req: &MultiPlatformExecuteProcessRequest,
    ) -> Option<ExecuteProcessRequest> {
      if self.is_compatible {
        Some(
          req
            .0
            .get(&(Platform::None, Platform::None))
            .unwrap()
            .clone(),
        )
      } else {
        None
      }
    }
  }
}
