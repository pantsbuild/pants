use crate::{BackoffConfig, Health, Serverset};
use futures01::{future, Future};
use parking_lot::Mutex;
use std;
use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;
use testutil::owned_string_vec;

fn backoff_config() -> BackoffConfig {
  BackoffConfig::new(Duration::from_millis(10), 2.0, Duration::from_millis(100)).unwrap()
}

#[test]
fn no_servers_is_error() {
  let servers: Vec<String> = vec![];
  Serverset::new(servers, fake_connect, 1, backoff_config())
    .expect_err("Want error constructing with no servers");
}

#[test]
fn one_request_works() {
  let mut rt = tokio::runtime::Runtime::new().unwrap();
  let s = Serverset::new(
    owned_string_vec(&["good"]),
    fake_connect,
    1,
    backoff_config(),
  )
  .unwrap();

  assert_eq!(rt.block_on(s.next()).unwrap().0, "good".to_owned());
}

#[test]
fn round_robins() {
  let mut rt = tokio::runtime::Runtime::new().unwrap();
  let s = Serverset::new(
    owned_string_vec(&["good", "bad"]),
    fake_connect,
    2,
    backoff_config(),
  )
  .unwrap();

  expect_both(&mut rt, &s, 2);
}

#[test]
fn handles_overflow_internally() {
  let mut rt = tokio::runtime::Runtime::new().unwrap();
  let s = Serverset::new(
    owned_string_vec(&["good", "bad"]),
    fake_connect,
    2,
    backoff_config(),
  )
  .unwrap();
  s.inner.lock().next_server = std::usize::MAX;

  // 3 because we may skip some values if the number of servers isn't a factor of
  // std::usize::MAX, so we make sure to go around them all again after overflowing.
  expect_both(&mut rt, &s, 3)
}

fn unwrap<T: std::fmt::Debug>(wrapped: Arc<Mutex<T>>) -> T {
  Arc::try_unwrap(wrapped)
    .expect("Couldn't unwrap")
    .into_inner()
}

#[test]
fn skips_unhealthy() {
  let mut rt = tokio::runtime::Runtime::new().unwrap();
  let s = Serverset::new(
    owned_string_vec(&["good", "bad"]),
    fake_connect,
    2,
    backoff_config(),
  )
  .unwrap();

  mark_bad_as_bad(&mut rt, &s, Health::Unhealthy);

  expect_only_good(&mut rt, &s, Duration::from_millis(10));
}

#[test]
fn reattempts_unhealthy() {
  let mut rt = tokio::runtime::Runtime::new().unwrap();
  let s = Serverset::new(
    owned_string_vec(&["good", "bad"]),
    fake_connect,
    2,
    backoff_config(),
  )
  .unwrap();

  mark_bad_as_bad(&mut rt, &s, Health::Unhealthy);

  expect_only_good(&mut rt, &s, Duration::from_millis(10));

  expect_both(&mut rt, &s, 3);
}

#[test]
fn backoff_when_unhealthy() {
  let mut rt = tokio::runtime::Runtime::new().unwrap();
  let s = Serverset::new(
    owned_string_vec(&["good", "bad"]),
    fake_connect,
    2,
    backoff_config(),
  )
  .unwrap();

  mark_bad_as_bad(&mut rt, &s, Health::Unhealthy);

  expect_only_good(&mut rt, &s, Duration::from_millis(10));

  // mark_bad_as_bad asserts that we attempted to use the bad server as a side effect, so this
  // checks that we did re-use the server after the lame period.
  mark_bad_as_bad(&mut rt, &s, Health::Unhealthy);

  expect_only_good(&mut rt, &s, Duration::from_millis(20));

  mark_bad_as_bad(&mut rt, &s, Health::Unhealthy);

  expect_only_good(&mut rt, &s, Duration::from_millis(40));

  expect_both(&mut rt, &s, 3);
}

#[test]
fn waits_if_all_unhealthy() {
  let backoff_config = backoff_config();
  let s = Serverset::new(
    owned_string_vec(&["good", "bad"]),
    fake_connect,
    2,
    backoff_config,
  )
  .unwrap();
  let mut runtime = tokio::runtime::Runtime::new().unwrap();

  // We will get an address 4 times, and mark it as unhealthy each of those times.
  // That means that each server will be marked bad twice, which according to our backoff config
  // means they should be marked as unavailable for 20ms each.
  for _ in 0..4 {
    let s = s.clone();
    let (_server, token) = runtime.block_on(s.next()).unwrap();
    s.report_health(token, Health::Unhealthy);
  }

  let start = std::time::Instant::now();

  // This should take at least 20ms because both servers are marked as unhealthy.
  let _ = runtime.block_on(s.next()).unwrap();

  // Make sure we waited for at least 10ms; we should have waited 20ms, but it may have taken a
  // little time to mark a server as unhealthy, so we have some padding between what we expect
  // (20ms) and what we assert (10ms).
  let elapsed = start.elapsed();
  assert!(
    elapsed > Duration::from_millis(10),
    "Waited for {:?} (less than expected)",
    elapsed
  );
}

fn expect_both(
  runtime: &mut tokio::runtime::Runtime,
  s: &Serverset<String>,
  repetitions: usize,
) {
  let visited = Arc::new(Mutex::new(HashSet::new()));

  runtime
    .block_on(future::join_all(
      (0..repetitions)
        .into_iter()
        .map(|_| {
          let saw = visited.clone();
          let s = s.clone();
          s.next().map(move |(server, token)| {
            saw.lock().insert(server);
            s.report_health(token, Health::Healthy)
          })
        })
        .collect::<Vec<_>>(),
    ))
    .unwrap();

  let expect: HashSet<_> = owned_string_vec(&["good", "bad"]).into_iter().collect();
  assert_eq!(unwrap(visited), expect);
}

fn mark_bad_as_bad(
  runtime: &mut tokio::runtime::Runtime,
  s: &Serverset<String>,
  health: Health,
) {
  let mark_bad_as_baded_bad = Arc::new(Mutex::new(false));
  for _ in 0..2 {
    let s = s.clone();
    let mark_bad_as_baded_bad = mark_bad_as_baded_bad.clone();
    let (server, token) = runtime.block_on(s.next()).unwrap();
    if &server == "bad" {
      *mark_bad_as_baded_bad.lock() = true;
      s.report_health(token, health);
    } else {
      s.report_health(token, Health::Healthy);
    }
  }
  assert!(
    *mark_bad_as_baded_bad.lock(),
    "Wasn't offered bad as a possible server, so didn't mark it bad"
  );
}

fn expect_only_good(
  runtime: &mut tokio::runtime::Runtime,
  s: &Serverset<String>,
  duration: Duration,
) {
  let buffer = Duration::from_millis(1);

  let start = std::time::Instant::now();
  let should_break = Arc::new(Mutex::new(false));
  let did_get_at_least_one_good = Arc::new(Mutex::new(false));
  while !*should_break.lock() {
    let s = s.clone();
    let should_break = should_break.clone();
    let did_get_at_least_one_good = did_get_at_least_one_good.clone();
    let (server, token) = runtime.block_on(s.next()).unwrap();
    if start.elapsed() < duration - buffer {
      assert_eq!("good", &server);
      *did_get_at_least_one_good.lock() = true;
    } else {
      *should_break.lock() = true;
    }
    s.report_health(token, Health::Healthy);
  }

  assert!(*did_get_at_least_one_good.lock());

  std::thread::sleep(buffer * 2);
}

/// For tests, we just use Strings as servers, as it's an easy type we can make from addresses.
fn fake_connect(s: &str) -> String {
  s.to_owned()
}
