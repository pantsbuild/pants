use super::{
  CommandRunner, ExecuteProcessRequest, FallibleExecuteProcessResult,
  MultiPlatformExecuteProcessRequest,
};
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

  fn speculate(
    &self,
    req: MultiPlatformExecuteProcessRequest,
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

impl CommandRunner for SpeculatingCommandRunner {
  fn get_compatible_request(
    &self,
    req: &MultiPlatformExecuteProcessRequest,
  ) -> Option<ExecuteProcessRequest> {
    match (
      self.primary.get_compatible_request(req),
      self.secondary.get_compatible_request(req),
    ) {
      (Some(req), _) => Some(req.clone()),
      (_, Some(req)) => Some(req.clone()),
      _ => None,
    }
  }

  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    match (
      self.primary.get_compatible_request(&req),
      self.secondary.get_compatible_request(&req),
    ) {
      (Some(_), Some(_)) => self.speculate(req, workunit_store),
      (Some(_), None) => self.primary.run(req, workunit_store),
      (None, Some(_)) => self.secondary.run(req, workunit_store),
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
  use workunit_store::WorkUnitStore;

  use super::{
    CommandRunner, ExecuteProcessRequest, FallibleExecuteProcessResult,
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
      run_speculation_test(50, 100, 25, false, false, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m1")]
  }

  #[test]
  fn first_req_slow_fail() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(100, 0, 10, true, false, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap().stdout, Bytes::from("m2")]
  }

  #[test]
  fn first_req_fast_fail() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(50, 100, 25, true, false, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap_err(), Bytes::from("m1")]
  }

  #[test]
  fn second_req_fast_fail() {
    let (result, call_counter, finished_counter) =
      run_speculation_test(100, 0, 10, true, true, true, true);
    assert_eq![2, *call_counter.lock().unwrap()];
    assert_eq![1, *finished_counter.lock().unwrap()];
    assert_eq![result.unwrap_err(), Bytes::from("m2")]
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
      run_speculation_test(50, 50, 25, false, false, true, true);
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
    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    let execute_request = echo_foo_request();
    let msg1: String = "m1".into();
    let msg2: String = "m2".into();
    let workunit_store = WorkUnitStore::new();
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
      runtime.block_on(runner.run(execute_request, workunit_store)),
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
      _workunit_store: WorkUnitStore,
    ) -> BoxFuture<FallibleExecuteProcessResult, String> {
      let delay = Delay::new(Instant::now() + self.delay);
      let exec_result = self.result.clone();
      let command_runner = self.clone();
      command_runner.incr_call_counter();
      delay
        .then(move |delay_res| match delay_res {
          Ok(_) => {
            command_runner.incr_finished_counter();
            exec_result
          }
          Err(_) => Err(String::from("Timer failed during testing")),
        })
        .to_boxed()
    }

    fn get_compatible_request(
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
