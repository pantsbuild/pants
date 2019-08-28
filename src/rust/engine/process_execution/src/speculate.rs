use super::{CommandRunner, ExecuteProcessRequest, FallibleExecuteProcessResult};
use boxfuture::{BoxFuture, Boxable};
use futures::future::{err, ok, Future};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio_timer::Delay;
use workunit_store::WorkUnitStore;

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
}

impl CommandRunner for SpeculatingCommandRunner {
  fn run(
    &self,
    req: ExecuteProcessRequest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let command_runner = self.clone();
    let workunit_store_clone = workunit_store.clone();
    let req_2 = req.clone();
    let delay = Delay::new(Instant::now() + self.speculation_timeout);
    self
      .primary
      .run(req, workunit_store)
      .select(delay.then(move |_| command_runner.secondary.run(req_2, workunit_store_clone)))
      .then(|raced_result| match raced_result {
        Ok((successful_res, _outstanding_req)) => {
          ok::<FallibleExecuteProcessResult, String>(successful_res).to_boxed()
        }
        Err((failed_res, _outstanding_req)) => {
          err::<FallibleExecuteProcessResult, String>(failed_res).to_boxed()
        }
      })
      .to_boxed()
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
  use workunit_store::WorkUnitStore;

  use super::{
    CommandRunner, ExecuteProcessRequest, FallibleExecuteProcessResult, SpeculatingCommandRunner,
  };

  #[test]
  fn test_no_speculation() {
    let (result, call_counter) = run_speculation_test(0, 0, 100, false, false);
    assert_eq![1, *call_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m1")];
  }

  #[test]
  fn test_speculate() {
    let (result, call_counter) = run_speculation_test(100, 0, 10, false, false);
    assert_eq![1, *call_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m2")]
  }

  #[test]
  fn first_req_slow_success() {
    let (result, call_counter) = run_speculation_test(15, 10, 10, false, false);
    assert_eq![1, *call_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m1")]
  }

  #[test]
  fn first_req_slow_fail() {
    let (result, call_counter) = run_speculation_test(100, 0, 10, true, false);
    assert_eq![1, *call_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m2")]
  }

  #[test]
  fn first_req_fast_fail() {
    let (result, call_counter) = run_speculation_test(15, 10, 10, true, false);
    assert_eq![1, *call_counter.lock().unwrap()];
    assert_eq![result.unwrap_err(), Bytes::from("m1")]
  }

  #[test]
  fn second_req_fast_fail() {
    let (result, call_counter) = run_speculation_test(100, 0, 10, true, true);
    assert_eq![1, *call_counter.lock().unwrap()];
    assert_eq![result.unwrap_err(), Bytes::from("m2")]
  }

  fn run_speculation_test(
    r1_latency_ms: u64,
    r2_latency_ms: u64,
    speculation_delay_ms: u64,
    r1_is_err: bool,
    r2_is_err: bool,
  ) -> (
    Result<FallibleExecuteProcessResult, String>,
    Arc<Mutex<u32>>,
  ) {
    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    let execute_request = echo_foo_request();
    let msg1: String = "m1".into();
    let msg2: String = "m2".into();
    let workunit_store = WorkUnitStore::new();
    let call_counter = Arc::new(Mutex::new(0));
    let runner = SpeculatingCommandRunner::new(
      Box::new(make_delayed_command_runner(
        msg1.clone(),
        r1_latency_ms,
        r1_is_err,
        call_counter.clone(),
      )),
      Box::new(make_delayed_command_runner(
        msg2.clone(),
        r2_latency_ms,
        r2_is_err,
        call_counter.clone(),
      )),
      Duration::from_millis(speculation_delay_ms),
    );
    (
      runtime.block_on(runner.run(execute_request, workunit_store)),
      call_counter,
    )
  }

  fn make_delayed_command_runner(
    msg: String,
    delay: u64,
    is_err: bool,
    call_counter: Arc<Mutex<u32>>,
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
    DelayedCommandRunner::new(Duration::from_millis(delay), result, call_counter)
  }

  #[derive(Clone)]
  struct DelayedCommandRunner {
    delay: Duration,
    result: Result<FallibleExecuteProcessResult, String>,
    call_counter: Arc<Mutex<u32>>,
  }

  impl DelayedCommandRunner {
    pub fn new(
      delay: Duration,
      result: Result<FallibleExecuteProcessResult, String>,
      call_counter: Arc<Mutex<u32>>,
    ) -> DelayedCommandRunner {
      DelayedCommandRunner {
        delay: delay,
        result: result,
        call_counter: call_counter,
      }
    }
    fn incr_call_counter(&self) {
      let mut calls = self.call_counter.lock().unwrap();
      *calls += 1;
    }
  }

  impl CommandRunner for DelayedCommandRunner {
    fn run(
      &self,
      _req: ExecuteProcessRequest,
      _workunit_store: WorkUnitStore,
    ) -> BoxFuture<FallibleExecuteProcessResult, String> {
      let delay = Delay::new(Instant::now() + self.delay);
      let exec_result = self.result.clone();
      let command_runner = self.clone();
      delay
        .then(move |delay_res| match delay_res {
          Ok(_) => {
            command_runner.incr_call_counter();
            exec_result
          }
          Err(_) => Err(String::from("Timer failed during testing")),
        })
        .to_boxed()
    }
  }
}
