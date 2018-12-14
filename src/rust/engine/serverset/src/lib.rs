// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy,
    default_trait_access,
    expl_impl_clone_on_copy,
    if_not_else,
    needless_continue,
    single_match_else,
    unseparated_literal_suffix,
    used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Subjective style.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(len_without_is_empty, redundant_field_names)
)]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(new_without_default, new_without_default_derive)
)]

extern crate boxfuture;
extern crate futures;
extern crate futures_timer;
extern crate num_rational;
extern crate parking_lot;

use boxfuture::{BoxFuture, Boxable};
use futures::Future;
use futures_timer::Delay;
use parking_lot::Mutex;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

///
/// A collection of resources which are observed to be healthy or unhealthy.
/// Getting the next resource skips any which are mark_bad_as_baded unhealthy, and will re-try unhealthy
/// resources at an exponentially backed off interval. Unhealthy resources mark_bad_as_baded healthy will ease
/// back into rotation with exponential ease-in.
///
pub struct Serverset<T> {
  inner: Arc<Inner<T>>,
}

impl<T> Clone for Serverset<T> {
  fn clone(&self) -> Self {
    Serverset {
      inner: self.inner.clone(),
    }
  }
}

///
/// An opaque value which can be passed to Serverset::callback to indicate for which server the
/// callback is being made.
///
/// Do not rely on any implementation details of this type, including its Debug representation.
/// It is liable to change at any time (though will continue to implement the traits which it
/// implements in some way which may not be stable).
///
#[derive(Clone, Copy, Debug)]
pub struct CallbackToken {
  index: usize,
}

struct Inner<T> {
  servers: Vec<Backend<T>>,

  // Only visible for testing
  pub(crate) next: AtomicUsize,

  failure_initial_lame: Duration,

  failure_backoff_ratio: num_rational::Ratio<u32>,

  failure_max_lame: Duration,
}

#[derive(Clone, Copy, Debug)]
pub enum Health {
  Healthy,
  Unhealthy,
}

#[derive(Debug)]
struct UnhealthyInfo {
  unhealthy_since: Instant,
  next_attempt_after: Duration,
}

#[derive(Debug)]
struct Backend<T> {
  server: T,
  unhealthy_info: Arc<Mutex<Option<UnhealthyInfo>>>,
}

#[derive(Clone, Copy, Debug)]
pub struct BackoffConfig {
  ///
  /// The time a backend will be skipped after it is first reported unhealthy.
  ///
  pub initial_lame: Duration,
  ///
  /// Ratio by which to multiply the most recent lame duration if a backend continues to be
  /// unhealthy.
  ///
  /// The inverse is used when easing back in after health recovery.
  pub backoff_ratio: f64,

  ///
  /// Maximum duration to wait between attempts.
  ///
  pub max_lame: Duration,
}

impl<T: Clone + Send + Sync + 'static> Serverset<T> {
  pub fn new(servers: Vec<T>, backoff_config: BackoffConfig) -> Result<Self, String> {
    if servers.is_empty() {
      return Err("Must supply some servers".to_owned());
    }

    let BackoffConfig {
      initial_lame,
      backoff_ratio,
      max_lame,
    } = backoff_config;

    if backoff_ratio < 1.0 {
      return Err(format!(
        "Failure backoff ratio must be at least 1, got: {}",
        backoff_ratio
      ));
    }
    let backoff_ratio =
      num_rational::Ratio::<i8>::approximate_float(backoff_ratio).ok_or_else(|| {
        format!(
          "Couldn't find reasonable backoff ratio for {}",
          backoff_ratio
        )
      })?;
    let backoff_ratio =
      num_rational::Ratio::new(*backoff_ratio.numer() as u32, *backoff_ratio.denom() as u32);
    Ok(Serverset {
      inner: Arc::new(Inner {
        servers: servers
          .into_iter()
          .map(|s| Backend {
            server: s,
            unhealthy_info: Arc::new(Mutex::new(None)),
          }).collect(),
        next: AtomicUsize::new(0),
        failure_initial_lame: initial_lame,
        failure_backoff_ratio: backoff_ratio,
        failure_max_lame: max_lame,
      }),
    })
  }

  ///
  /// Get the next (probably) healthy backend to use.
  ///
  /// The caller will be given a backend to use, and should call ServerSet::callback with the
  /// supplied token, and the observed health of that backend.
  ///
  /// If the callback is not called, the health status of the server will not be changed from its
  /// last known status.
  ///
  /// If all resources are unhealthy, the returned Future will delay until a resource becomes
  /// healthy.
  ///
  /// No efforts are currently made to avoid a thundering heard at few healthy servers (or the the
  /// first server to become healthy after all are unhealthy).
  ///
  pub fn next(&self) -> BoxFuture<(T, CallbackToken), String> {
    let now = Instant::now();
    let server_count = self.inner.servers.len();

    let mut earliest_future = None;
    for _ in 0..server_count {
      let i = self.inner.next.fetch_add(1, Ordering::Relaxed) % server_count;
      let server = &self.inner.servers[i];
      let unhealthy_info = server.unhealthy_info.lock();
      if let Some(ref unhealthy_info) = *unhealthy_info {
        // Server is unhealthy. Note when it will become healthy.

        let healthy_at = unhealthy_info.unhealthy_since + unhealthy_info.next_attempt_after;

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
      return futures::future::ok((server.server.clone(), CallbackToken { index: i })).to_boxed();
    }
    // Unwrap is safe because if we hadn't populated earliest_future, we would already have returned.
    let (index, instant) = earliest_future.unwrap();
    let server = self.inner.servers[index].server.clone();
    // Note that Delay::new_at(time in the past) gets immediately scheduled.
    Delay::new_at(instant)
      .map_err(|err| format!("Error delaying for serverset: {}", err))
      .map(move |()| (server, CallbackToken { index }))
      .to_boxed()
  }

  fn multiply(duration: Duration, fraction: num_rational::Ratio<u32>) -> Duration {
    (duration * *fraction.numer()) / *fraction.denom()
  }

  pub fn callback(&self, callback_token: CallbackToken, health: Health) {
    let mut unhealthy_info = self.inner.servers[callback_token.index]
      .unhealthy_info
      .lock();
    match health {
      Health::Unhealthy => {
        if unhealthy_info.is_some() {
          if let Some(ref mut unhealthy_info) = *unhealthy_info {
            unhealthy_info.unhealthy_since = Instant::now();
            // failure_backoff_ratio's numer and denom both fit in u8s, so hopefully this won't
            // overflow or lose too much precision...
            let next_exponential_duration = Self::multiply(
              unhealthy_info.next_attempt_after,
              self.inner.failure_backoff_ratio,
            );
            unhealthy_info.next_attempt_after =
              std::cmp::min(next_exponential_duration, self.inner.failure_max_lame);
          }
        } else {
          *unhealthy_info = Some(UnhealthyInfo {
            unhealthy_since: Instant::now(),
            next_attempt_after: self.inner.failure_initial_lame,
          });
        }
      }
      Health::Healthy => {
        if unhealthy_info.is_some() {
          let mut reset = false;
          if let Some(ref mut unhealthy_info) = *unhealthy_info {
            reset = unhealthy_info.next_attempt_after <= self.inner.failure_initial_lame;

            if !reset {
              unhealthy_info.unhealthy_since = Instant::now();
              // failure_backoff_ratio's numer and denom both fit in u8s, so hopefully this won't
              // overflow or lose too much precision...
              unhealthy_info.next_attempt_after = Self::multiply(
                unhealthy_info.next_attempt_after,
                self.inner.failure_backoff_ratio.recip(),
              );
            }
          }
          if reset {
            *unhealthy_info = None;
          }
        }
      }
    }
  }
}

impl<T: std::fmt::Debug> std::fmt::Debug for Serverset<T> {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    write!(f, "Serverset {{ {:?} }}", self.inner.servers);
    Ok(())
  }
}

#[cfg(test)]
mod tests {
  use super::{BackoffConfig, Health, Serverset};
  use futures::{self, Future};
  use parking_lot::Mutex;
  use std;
  use std::collections::HashSet;
  use std::sync::atomic::Ordering;
  use std::sync::Arc;
  use std::time::Duration;

  fn backoff_config() -> BackoffConfig {
    BackoffConfig {
      initial_lame: Duration::from_millis(10),
      backoff_ratio: 2.0,
      max_lame: Duration::from_millis(100),
    }
  }

  #[test]
  fn no_servers_is_error() {
    let servers: Vec<String> = vec![];
    Serverset::new(servers, backoff_config()).expect_err("Want error constructing with no servers");
  }

  #[test]
  fn round_robins() {
    let s = Serverset::new(vec!["good", "bad"], backoff_config()).unwrap();

    expect_both(&s, 2);
  }

  #[test]
  fn handles_overflow_internally() {
    let s = Serverset::new(vec!["good", "bad"], backoff_config()).unwrap();
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
    let s = Serverset::new(vec!["good", "bad"], backoff_config()).unwrap();

    mark_bad_as_bad(&s, Health::Unhealthy);

    expect_only_good(&s, Duration::from_millis(10));
  }

  #[test]
  fn reattempts_unhealthy() {
    let s = Serverset::new(vec!["good", "bad"], backoff_config()).unwrap();

    mark_bad_as_bad(&s, Health::Unhealthy);

    expect_only_good(&s, Duration::from_millis(10));

    expect_both(&s, 2);
  }

  #[test]
  fn backoff_when_unhealthy() {
    let s = Serverset::new(vec!["good", "bad"], backoff_config()).unwrap();

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
    let s = Serverset::new(vec!["good", "bad"], backoff_config).unwrap();

    for _ in 0..2 {
      s.next()
        .map(|(_server, token)| s.callback(token, Health::Unhealthy))
        .wait()
        .unwrap();
    }

    let start = std::time::Instant::now();

    s.next().wait().unwrap();

    assert!(start.elapsed() > backoff_config.initial_lame)
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
            s.callback(token, Health::Healthy)
          })
        }).collect::<Vec<_>>(),
    ).wait()
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
            s.callback(token, health);
          } else {
            s.callback(token, Health::Healthy);
          }
        }).wait()
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
          s.callback(token, Health::Healthy);
        }).wait()
        .unwrap();
    }

    std::thread::sleep(buffer * 2);
  }
}
