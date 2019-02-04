// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(
  clippy::new_without_default,
  clippy::new_without_default_derive,
  clippy::new_ret_no_self
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use futures;
use futures_timer;

use boxfuture::{BoxFuture, Boxable};
use futures::Future;
use futures_timer::Delay;
use parking_lot::Mutex;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

mod retry;
pub use crate::retry::Retry;

///
/// A collection of resources which are observed to be healthy or unhealthy.
/// Getting the next resource skips any which are mark_bad_as_baded unhealthy, and will re-try unhealthy
/// resources at an exponentially backed off interval. Unhealthy resources mark_bad_as_baded healthy will ease
/// back into rotation with exponential ease-in.
///
pub struct Serverset<T> {
  inner: Arc<Inner<T>>,
}

impl<T: Clone + Send + Sync + 'static> Clone for Serverset<T> {
  fn clone(&self) -> Self {
    Serverset {
      inner: self.inner.clone(),
    }
  }
}

///
/// An opaque value which can be passed to Serverset::report_health to indicate for which server the
/// report is being made.
///
/// Do not rely on any implementation details of this type, including its Debug representation.
/// It is liable to change at any time (though will continue to implement the traits which it
/// implements in some way which may not be stable).
///
#[derive(Clone, Copy, Debug)]
#[must_use]
pub struct HealthReportToken {
  index: usize,
}

struct Inner<T> {
  servers: Vec<Backend<T>>,

  // Only visible for testing
  pub(crate) next: AtomicUsize,

  backoff_config: BackoffConfig,

  timer_handle: futures_timer::TimerHandle,
}

#[derive(Clone, Copy, Debug)]
pub enum Health {
  Healthy,
  Unhealthy,
}

// Ideally this would use Durations when https://github.com/rust-lang/rust/issues/54361 stabilises.
#[derive(Debug)]
struct UnhealthyInfo {
  unhealthy_since: Instant,
  next_attempt_after_millis: f64,
}

impl UnhealthyInfo {
  fn new(backoff_config: BackoffConfig) -> UnhealthyInfo {
    UnhealthyInfo {
      unhealthy_since: Instant::now(),
      next_attempt_after_millis: backoff_config.initial_lame_millis as f64,
    }
  }

  fn healthy_at(&self) -> Instant {
    self.unhealthy_since + Duration::from_millis(self.next_attempt_after_millis as u64)
  }

  fn increase_backoff(&mut self, backoff_config: BackoffConfig) {
    self.unhealthy_since = Instant::now();
    self.next_attempt_after_millis = f64::min(
      backoff_config.max_lame_millis,
      self.next_attempt_after_millis * backoff_config.ratio,
    );
  }

  fn decrease_backoff(mut self, backoff_config: BackoffConfig) -> Option<UnhealthyInfo> {
    self.unhealthy_since = Instant::now();
    let next_value = self.next_attempt_after_millis / backoff_config.ratio;
    if next_value < backoff_config.initial_lame_millis {
      None
    } else {
      self.next_attempt_after_millis = next_value;
      Some(self)
    }
  }
}

#[derive(Debug)]
struct Backend<T> {
  server: T,
  unhealthy_info: Arc<Mutex<Option<UnhealthyInfo>>>,
}

// Ideally this would use Durations when https://github.com/rust-lang/rust/issues/54361 stabilises.
#[derive(Clone, Copy, Debug)]
pub struct BackoffConfig {
  ///
  /// The time a backend will be skipped after it is first reported unhealthy.
  ///
  initial_lame_millis: f64,

  ///
  /// Ratio by which to multiply the most recent lame duration if a backend continues to be
  /// unhealthy.
  ///
  /// The inverse is used when easing back in after health recovery.
  ratio: f64,

  ///
  /// Maximum duration to wait between attempts.
  ///
  max_lame_millis: f64,
}

impl BackoffConfig {
  pub fn new(
    initial_lame: Duration,
    ratio: f64,
    max_lame: Duration,
  ) -> Result<BackoffConfig, String> {
    if ratio < 1.0 {
      return Err(format!(
        "Failure backoff ratio must be at least 1, got: {}",
        ratio
      ));
    }

    let initial_lame_millis =
      initial_lame.as_secs() as f64 * 1000_f64 + f64::from(initial_lame.subsec_millis());
    let max_lame_millis =
      max_lame.as_secs() as f64 * 1000_f64 + f64::from(max_lame.subsec_millis());

    Ok(BackoffConfig {
      initial_lame_millis,
      ratio,
      max_lame_millis,
    })
  }
}

impl<T: Clone + Send + Sync + 'static> Serverset<T> {
  pub fn new(
    servers: Vec<T>,
    backoff_config: BackoffConfig,
    timer_handle: futures_timer::TimerHandle,
  ) -> Result<Self, String> {
    if servers.is_empty() {
      return Err("Must supply some servers".to_owned());
    }

    Ok(Serverset {
      inner: Arc::new(Inner {
        servers: servers
          .into_iter()
          .map(|s| Backend {
            server: s,
            unhealthy_info: Arc::new(Mutex::new(None)),
          })
          .collect(),
        next: AtomicUsize::new(0),
        backoff_config,
        timer_handle,
      }),
    })
  }

  ///
  /// Get the next (probably) healthy backend to use.
  ///
  /// The caller will be given a backend to use, and should call Serverset::report_health with the
  /// supplied token, and the observed health of that backend.
  ///
  /// If report_health is not called, the health status of the server will not be changed from its
  /// last known status.
  ///
  /// If all resources are unhealthy, the returned Future will delay until a resource becomes
  /// healthy.
  ///
  /// No efforts are currently made to avoid a thundering heard at few healthy servers (or the the
  /// first server to become healthy after all are unhealthy).
  ///
  pub fn next(&self) -> BoxFuture<(T, HealthReportToken), String> {
    let now = Instant::now();
    let server_count = self.inner.servers.len();

    let mut earliest_future = None;
    for _ in 0..server_count {
      let i = self.inner.next.fetch_add(1, Ordering::Relaxed) % server_count;
      let server = &self.inner.servers[i];
      let unhealthy_info = server.unhealthy_info.lock();
      if let Some(ref unhealthy_info) = *unhealthy_info {
        // Server is unhealthy. Note when it will become healthy.

        let healthy_at = unhealthy_info.healthy_at();

        if healthy_at > now {
          let healthy_sooner_than_previous = if let Some((_, previous_healthy_at)) = earliest_future
          {
            previous_healthy_at > healthy_at
          } else {
            true
          };

          if healthy_sooner_than_previous {
            earliest_future = Some((i, healthy_at));
          }
          continue;
        }
      }
      // A healthy server! Use it!
      return futures::future::ok((server.server.clone(), HealthReportToken { index: i }))
        .to_boxed();
    }
    // Unwrap is safe because if we hadn't populated earliest_future, we would already have returned.
    let (index, instant) = earliest_future.unwrap();
    let server = self.inner.servers[index].server.clone();
    // Note that Delay::new_at(time in the past) gets immediately scheduled.
    Delay::new_handle(instant, self.inner.timer_handle.clone())
      .map_err(|err| format!("Error delaying for serverset: {}", err))
      .map(move |()| (server, HealthReportToken { index }))
      .to_boxed()
  }

  pub fn report_health(&self, token: HealthReportToken, health: Health) {
    let mut unhealthy_info = self.inner.servers[token.index].unhealthy_info.lock();
    match health {
      Health::Unhealthy => {
        if unhealthy_info.is_some() {
          if let Some(ref mut unhealthy_info) = *unhealthy_info {
            unhealthy_info.increase_backoff(self.inner.backoff_config);
          }
        } else {
          *unhealthy_info = Some(UnhealthyInfo::new(self.inner.backoff_config));
        }
      }
      Health::Healthy => {
        if unhealthy_info.is_some() {
          *unhealthy_info = unhealthy_info
            .take()
            .unwrap()
            .decrease_backoff(self.inner.backoff_config);
        }
      }
    }
  }
}

impl<T: std::fmt::Debug> std::fmt::Debug for Serverset<T> {
  fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> Result<(), std::fmt::Error> {
    write!(f, "Serverset {{ {:?} }}", self.inner.servers)
  }
}

#[cfg(test)]
mod tests {
  use super::{BackoffConfig, Health, Serverset};
  use futures::{self, Future};
  use futures_timer::TimerHandle;
  use parking_lot::Mutex;
  use std;
  use std::collections::HashSet;
  use std::sync::atomic::Ordering;
  use std::sync::Arc;
  use std::time::Duration;

  fn backoff_config() -> BackoffConfig {
    BackoffConfig::new(Duration::from_millis(10), 2.0, Duration::from_millis(100)).unwrap()
  }

  #[test]
  fn no_servers_is_error() {
    let servers: Vec<String> = vec![];
    Serverset::new(servers, backoff_config(), TimerHandle::default())
      .expect_err("Want error constructing with no servers");
  }

  #[test]
  fn round_robins() {
    let s = Serverset::new(
      vec!["good", "bad"],
      backoff_config(),
      TimerHandle::default(),
    )
    .unwrap();

    expect_both(&s, 2);
  }

  #[test]
  fn handles_overflow_internally() {
    let s = Serverset::new(
      vec!["good", "bad"],
      backoff_config(),
      TimerHandle::default(),
    )
    .unwrap();
    s.inner.next.store(std::usize::MAX, Ordering::SeqCst);

    // 3 because we may skip some values if the number of servers isn't a factor of
    // std::usize::MAX, so we make sure to go around them all again after overflowing.
    expect_both(&s, 3)
  }

  fn unwrap<T: std::fmt::Debug>(wrapped: Arc<Mutex<T>>) -> T {
    Arc::try_unwrap(wrapped)
      .expect("Couldn't unwrap")
      .into_inner()
  }

  #[test]
  fn skips_unhealthy() {
    let s = Serverset::new(
      vec!["good", "bad"],
      backoff_config(),
      TimerHandle::default(),
    )
    .unwrap();

    mark_bad_as_bad(&s, Health::Unhealthy);

    expect_only_good(&s, Duration::from_millis(10));
  }

  #[test]
  fn reattempts_unhealthy() {
    let s = Serverset::new(
      vec!["good", "bad"],
      backoff_config(),
      TimerHandle::default(),
    )
    .unwrap();

    mark_bad_as_bad(&s, Health::Unhealthy);

    expect_only_good(&s, Duration::from_millis(10));

    expect_both(&s, 2);
  }

  #[test]
  fn backoff_when_unhealthy() {
    let s = Serverset::new(
      vec!["good", "bad"],
      backoff_config(),
      TimerHandle::default(),
    )
    .unwrap();

    mark_bad_as_bad(&s, Health::Unhealthy);

    expect_only_good(&s, Duration::from_millis(10));

    mark_bad_as_bad(&s, Health::Unhealthy);

    expect_only_good(&s, Duration::from_millis(20));

    mark_bad_as_bad(&s, Health::Unhealthy);

    expect_only_good(&s, Duration::from_millis(40));

    mark_bad_as_bad(&s, Health::Healthy);

    expect_only_good(&s, Duration::from_millis(20));

    mark_bad_as_bad(&s, Health::Healthy);

    expect_only_good(&s, Duration::from_millis(10));

    mark_bad_as_bad(&s, Health::Healthy);

    expect_both(&s, 2);
  }

  #[test]
  fn waits_if_all_unhealthy() {
    let backoff_config = backoff_config();
    let s = Serverset::new(vec!["good", "bad"], backoff_config, TimerHandle::default()).unwrap();

    for _ in 0..2 {
      s.next()
        .map(|(_server, token)| s.report_health(token, Health::Unhealthy))
        .wait()
        .unwrap();
    }

    let start = std::time::Instant::now();

    s.next().wait().unwrap();

    assert!(start.elapsed() > Duration::from_millis(10))
  }

  fn expect_both(s: &Serverset<&'static str>, repetitions: usize) {
    let visited = Arc::new(Mutex::new(HashSet::new()));

    futures::future::join_all(
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
    )
    .wait()
    .unwrap();

    let expect: HashSet<_> = vec!["good", "bad"].into_iter().collect();
    assert_eq!(unwrap(visited), expect);
  }

  fn mark_bad_as_bad(s: &Serverset<&'static str>, health: Health) {
    let mut mark_bad_as_baded_bad = false;
    for _ in 0..2 {
      s.next()
        .map(|(server, token)| {
          if server == "bad" {
            mark_bad_as_baded_bad = true;
            s.report_health(token, health);
          } else {
            s.report_health(token, Health::Healthy);
          }
        })
        .wait()
        .unwrap();
    }
    assert!(mark_bad_as_baded_bad);
  }

  fn expect_only_good(s: &Serverset<&'static str>, duration: Duration) {
    let buffer = Duration::from_millis(1);

    let start = std::time::Instant::now();
    while start.elapsed() < duration - buffer {
      s.next()
        .map(|(server, token)| {
          assert_eq!("good", server);
          s.report_health(token, Health::Healthy);
        })
        .wait()
        .unwrap();
    }

    std::thread::sleep(buffer * 2);
  }
}
