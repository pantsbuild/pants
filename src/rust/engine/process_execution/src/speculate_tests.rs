use crate::remote_tests::echo_foo_request;
use crate::speculate::SpeculatingCommandRunner;
use crate::{
  CommandRunner, Context, ExecuteProcessRequest, FallibleExecuteProcessResultWithPlatform,
  MultiPlatformExecuteProcessRequest, Platform, PlatformConstraint,
};
use boxfuture::{BoxFuture, Boxable};
use bytes::Bytes;
use futures01::future::Future;
use hashing::EMPTY_DIGEST;
use parking_lot::Mutex;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio;
use tokio_timer::Delay;

#[test]
fn test_no_speculation() {
  let (result, call_counter, finished_counter) =
    run_speculation_test(0, 0, 100, false, false, true, true);
  assert_eq![1, *call_counter.lock()];
  assert_eq![1, *finished_counter.lock()];
  assert_eq![result.unwrap().stdout, Bytes::from("m1")];
}

#[test]
fn test_speculate() {
  let (result, call_counter, finished_counter) =
    run_speculation_test(100, 0, 10, false, false, true, true);
  assert_eq![2, *call_counter.lock()];
  assert_eq![1, *finished_counter.lock()];
  assert_eq![result.unwrap().stdout, Bytes::from("m2")]
}

#[test]
fn first_req_slow_success() {
  let (result, call_counter, finished_counter) =
    run_speculation_test(500, 1000, 250, false, false, true, true);
  assert_eq![2, *call_counter.lock()];
  assert_eq![1, *finished_counter.lock()];
  assert_eq![result.unwrap().stdout, Bytes::from("m1")]
}

#[test]
fn first_req_slow_fail() {
  let (result, call_counter, finished_counter) =
    run_speculation_test(1000, 0, 100, true, false, true, true);
  assert_eq![2, *call_counter.lock()];
  assert_eq![1, *finished_counter.lock()];
  assert_eq![result.unwrap().stdout, Bytes::from("m2")]
}

#[test]
fn first_req_fast_fail() {
  let (result, call_counter, finished_counter) =
    run_speculation_test(500, 1000, 250, true, false, true, true);
  assert_eq![2, *call_counter.lock()];
  assert_eq![1, *finished_counter.lock()];
  assert_eq![result.unwrap_err(), Bytes::from("m1")]
}

#[test]
fn only_fail_on_primary_result() {
  let (result, call_counter, finished_counter) =
    run_speculation_test(1000, 0, 100, true, true, true, true);
  assert_eq![2, *call_counter.lock()];
  assert_eq![2, *finished_counter.lock()];
  assert_eq![result.unwrap_err(), Bytes::from("m1")]
}

#[test]
fn platform_compatible_with_1st_runs_once() {
  let (result, call_counter, finished_counter) =
    run_speculation_test(0, 0, 100, false, false, true, false);
  assert_eq![1, *call_counter.lock()];
  assert_eq![1, *finished_counter.lock()];
  assert_eq![result.unwrap().stdout, Bytes::from("m1")]
}

#[test]
fn platform_compatible_with_2nd_runs_once() {
  let (result, call_counter, finished_counter) =
    run_speculation_test(0, 0, 100, false, false, false, true);
  assert_eq![1, *call_counter.lock()];
  assert_eq![1, *finished_counter.lock()];
  assert_eq![result.unwrap().stdout, Bytes::from("m2")]
}

#[test]
fn platform_compatible_with_both_speculates() {
  let (result, call_counter, finished_counter) =
    run_speculation_test(1000, 1000, 500, false, false, true, true);
  assert_eq![2, *call_counter.lock()];
  assert_eq![1, *finished_counter.lock()];
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
  Result<FallibleExecuteProcessResultWithPlatform, String>,
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
    Ok(FallibleExecuteProcessResultWithPlatform {
      stdout: msg.into(),
      stderr: "".into(),
      exit_code: 0,
      output_directory: EMPTY_DIGEST,
      execution_attempts: vec![],
      platform: Platform::current().unwrap(),
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
  result: Result<FallibleExecuteProcessResultWithPlatform, String>,
  is_compatible: bool,
  call_counter: Arc<Mutex<u32>>,
  finished_counter: Arc<Mutex<u32>>,
}

impl DelayedCommandRunner {
  pub fn new(
    delay: Duration,
    result: Result<FallibleExecuteProcessResultWithPlatform, String>,
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
    let mut calls = self.call_counter.lock();
    *calls += 1;
  }
  fn incr_finished_counter(&self) {
    let mut calls = self.finished_counter.lock();
    *calls += 1;
  }
}

impl CommandRunner for DelayedCommandRunner {
  fn run(
    &self,
    _req: MultiPlatformExecuteProcessRequest,
    _context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResultWithPlatform, String> {
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
          .get(&(PlatformConstraint::None, PlatformConstraint::None))
          .unwrap()
          .clone(),
      )
    } else {
      None
    }
  }
}
