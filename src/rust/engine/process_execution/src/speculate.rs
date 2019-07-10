use std::time::{Duration, Instant};
use std::sync::Arc;
use tokio_timer::Delay;
use futures::future::{Either, Future, result};
use boxfuture::{BoxFuture, Boxable};
use super::{
  CommandRunner,
  ExecuteProcessRequest,
  FallibleExecuteProcessResult
};


#[derive(Clone)]
pub struct SpeculatingCommandRunner {
  primary: Arc<dyn CommandRunner>,
  secondary: Arc<dyn CommandRunner>,
  speculation_timeout_ms: u64,
}

impl SpeculatingCommandRunner {

  pub fn new(primary: Box<dyn CommandRunner>, secondary: Box<dyn CommandRunner>, speculation_timeout_ms: u64) -> SpeculatingCommandRunner {
    SpeculatingCommandRunner {
      primary: primary.into(),
      secondary: secondary.into(),
      speculation_timeout_ms: speculation_timeout_ms
    }
  }
}

impl CommandRunner for SpeculatingCommandRunner {
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let command_runner = self.clone();
    let req_2 = req.clone();
    let delay = Delay::new(Instant::now() + Duration::from_millis(self.speculation_timeout_ms));
    self.primary.run(req).select2(delay).then(
      move |raced_result| {
        match raced_result {
          // first request finished before delay, so pass it on
          Ok(Either::A((successful_first_req, _delay))) => result::<FallibleExecuteProcessResult, String>(Ok(successful_first_req)).to_boxed(),
          // delay finished before our first call, make a second, which returns either the first or second.
          Ok(Either::B((_delay_exceeded, outstanding_first_req))) => {
            command_runner.secondary.run(req_2).select(outstanding_first_req).map(
              // TODO(hrfuller) Need to impl Drop on something so that when the BoxFuture goes out of scope
              // we cancel a potential RPC, or locally, kill a subprocess. So we need to distinguish local vs. remote
              // requests and save enough state to BoxFuture or another abstraction around our execution results
              |(successful_res, _droppable_req)| { successful_res }
            ).map_err(
              // one of the requests failed. We fail fast and return here but we could potentially wait for the second request to finish.
              |(failed_res, _droppable_req)| { failed_res }
            ).to_boxed()
          },
          // NOTE(hrfuller), if the first request was remote and fails fast, we *could* launch a secondary local here.
          Err(Either::A((failed_first_res, _delay))) => result::<FallibleExecuteProcessResult, String>(Err(failed_first_res)).to_boxed(),
          // NOTE(hrfuller) timer failure seem unlikely but if it happens we could speculate here anyway.
          Err(Either::B((_failed_timer_res, outstanding_res))) => outstanding_res.to_boxed(),
        }
      }
    ).to_boxed()
  }
}


#[cfg(test)]
mod tests {
  use bytes::Bytes;
  use futures::future::Future;
  use hashing::{EMPTY_DIGEST};
  use boxfuture::{BoxFuture, Boxable};
  use std::time::{Duration, Instant};
  use tokio_timer::Delay;
  use tokio;
  use testutil::owned_string_vec;
  use std::collections::{BTreeMap, BTreeSet};

  use super::{
    SpeculatingCommandRunner,
    CommandRunner,
    ExecuteProcessRequest,
    FallibleExecuteProcessResult,
  };


  #[test]
  fn test_no_speculation() {
    let result = run_speculation_test(0, 0, 100, false, false,);
    assert_eq![result.unwrap().stdout, Bytes::from("m1")]
  }

  #[test]
  fn test_speculate() {
    let result = run_speculation_test(100, 0, 10, false, false);
    assert_eq![result.unwrap().stdout, Bytes::from("m2")]
  }

  #[test]
  fn first_req_slow_success() {
    let result = run_speculation_test(15, 10, 10, false, false);
    assert_eq![result.unwrap().stdout, Bytes::from("m1")]
  }

  #[test]
  fn first_req_slow_fail() {
    let result = run_speculation_test(100, 0, 10, true, false);
    assert_eq![result.unwrap().stdout, Bytes::from("m2")]
  }

  #[test]
  fn first_req_fast_fail() {
    let result = run_speculation_test(15, 10, 10, true, false);
    assert_eq![result.unwrap_err(), Bytes::from("m1")]
  }

  #[test]
  fn second_req_fast_fail() {
    let result = run_speculation_test(100, 0, 10, true, true);
    assert_eq![result.unwrap_err(), Bytes::from("m2")]
  }

  fn run_speculation_test(
    r1_latency_ms: u64,
    r2_latency_ms: u64,
    speculation_delay_ms: u64,
    r1_is_err: bool,
    r2_is_err: bool,
  ) -> Result<FallibleExecuteProcessResult, String> {
    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    let execute_request = echo_foo_request();
    let msg1: String = "m1".into();
    let msg2: String = "m2".into();
    let runner = SpeculatingCommandRunner::new(
      Box::new(make_delayed_command_runner(msg1.clone(), r1_latency_ms, r1_is_err)),
      Box::new(make_delayed_command_runner(msg2.clone(), r2_latency_ms, r2_is_err)),
      speculation_delay_ms,
    );
    runtime.block_on(runner.run(execute_request))
  }

  fn make_delayed_command_runner(msg: String, delay: u64, is_err: bool) -> DelayedCommandRunner {
    let (mut result, mut error) = (None, None);
    if is_err {
      error = Some(msg.into());
    } else {
      result = Some(FallibleExecuteProcessResult {
        stdout: msg.into(),
        stderr: "".into(),
        exit_code: 0,
        output_directory: EMPTY_DIGEST,
        execution_attempts: vec![],
      })
    }
    DelayedCommandRunner::new(delay, result, error)
  }

  fn echo_foo_request() -> ExecuteProcessRequest {
    ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
      input_files: EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(5000),
      description: "echo a foo".to_string(),
      jdk_home: None,
    }
  }

  struct DelayedCommandRunner {
    delay_ms: u64,
    result: Option<FallibleExecuteProcessResult>,
    error: Option<String>,
  }

  impl DelayedCommandRunner {
    pub fn new(delay_ms: u64, result: Option<FallibleExecuteProcessResult>, error: Option<String>) -> DelayedCommandRunner {
      DelayedCommandRunner {
        delay_ms: delay_ms,
        result: result,
        error: error,
      }
    }
  }

  impl CommandRunner for DelayedCommandRunner {
    fn run(&self, _req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String> {
      let delay = Delay::new(Instant::now() + Duration::from_millis(self.delay_ms));
      let exec_result = self.result.clone();
      let exec_error = self.error.clone();
      delay.then(move |delay_res| {
        match delay_res {
          Ok(_) => {
            if exec_result.is_some() {
              Ok(exec_result.unwrap())
            } else if exec_error.is_some() {
              Err(exec_error.unwrap())
            } else {
              Err(String::from("Generic command runner error!"))
            }
          },
          Err(e) => {
            println!["error is {:?}", e];
            Err(String::from("Timer failed during testing"))
          }
        }
      }).to_boxed()
    }
  }
}
