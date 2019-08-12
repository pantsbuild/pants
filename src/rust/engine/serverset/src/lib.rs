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
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use futures;

use boxfuture::{BoxFuture, Boxable};
use futures::Future;
use parking_lot::Mutex;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio_timer::Delay;

mod retry;
pub use crate::retry::Retry;

///
/// A collection of resources which are observed to be healthy or unhealthy.
/// Getting the next resource skips any which are mark_bad_as_baded unhealthy, and will re-try unhealthy
/// resources at an exponentially backed off interval. Unhealthy resources mark_bad_as_baded healthy will ease
/// back into rotation with exponential ease-in.
///
pub struct Serverset<T: Clone> {
  inner: Arc<Mutex<Inner<T>>>,
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
  server_index: usize,
}

struct Connection<T: Clone> {
  connection: T,
  server_index: usize,
}

struct Inner<T: Clone> {
  // Order is immutable through the lifetime of a Serverset, but contents of the Backend may change.
  servers: Vec<Backend>,
  // Only visible for testing
  pub(crate) next_server: usize,

  // Points into the servers list; may change over time.
  connections: Vec<Connection<T>>,
  next_connection: usize,

  connect: Box<Fn(&str) -> T + 'static + Send>,

  connection_limit: usize,

  backoff_config: BackoffConfig,
}

impl<T: Clone> Inner<T> {
  fn connect(&mut self) -> Option<(T, HealthReportToken)> {
    for _ in 0..self.servers.len() {
      let server_index = self.next_server % self.servers.len();
      self.next_server = self.next_server.wrapping_add(1);
      let server = &self.servers[server_index];
      if server.is_healthy() && !self.is_connected(server_index) {
        let connection = (self.connect)(&server.server);
        self.connections.push(Connection {
          connection: connection.clone(),
          server_index,
        });
        return Some((connection, HealthReportToken { server_index }));
      }
    }
    None
  }

  fn can_make_more_connections(&self) -> bool {
    let existing_connections = self.connections.len();
    existing_connections < self.connection_limit && self.servers.len() > existing_connections
  }

  fn is_connected(&self, server_index: usize) -> bool {
    self
      .connections
      .iter()
      .any(|connection| connection.server_index == server_index)
  }
}

#[derive(Clone, Copy, Debug)]
pub enum Health {
  Healthy,
  Unhealthy,
}

// Ideally this would use Durations when https://github.com/rust-lang/rust/issues/54361 stabilises.
#[derive(Clone, Copy, Debug)]
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
struct Backend {
  server: String,
  unhealthy_info: Option<UnhealthyInfo>,
}

impl Backend {
  fn is_healthy(&self) -> bool {
    if let Some(unhealthy_info) = self.unhealthy_info {
      unhealthy_info.healthy_at() < std::time::Instant::now()
    } else {
      true
    }
  }
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
  // Connect is currently infallible (i.e. doesn't return a Result type). This is because the only
  // type we use this for at the moment treats connections as infallible. If we start using a
  // Serverset for some type where connections can fail, we should consider factoring that into when
  // connections are considered unhealthy.
  pub fn new<Connect: Fn(&str) -> T + 'static + Send>(
    servers: Vec<String>,
    connect: Connect,
    connection_limit: usize,
    backoff_config: BackoffConfig,
  ) -> Result<Self, String> {
    if servers.is_empty() {
      return Err("Must supply some servers".to_owned());
    }
    if connection_limit == 0 {
      return Err("Must supply connection_limit greater than 0".to_owned());
    }
    let servers = servers
      .into_iter()
      .map(|server| Backend {
        server,
        unhealthy_info: None,
      })
      .collect();

    Ok(Serverset {
      inner: Arc::new(Mutex::new(Inner {
        servers,
        next_server: 0,
        connections: vec![],
        next_connection: 0,
        connect: Box::new(connect),
        connection_limit,
        backoff_config,
      })),
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
    let mut inner = self.inner.lock();

    if inner.can_make_more_connections() {
      // Find a healthy server without a connection, connect to it.
      if let Some(ret) = inner.connect() {
        inner.next_connection = inner.next_connection.wrapping_add(1);
        return futures::future::ok(ret).to_boxed();
      }
    }

    if !inner.connections.is_empty() {
      let next_connection = inner.next_connection;
      inner.next_connection = inner.next_connection.wrapping_add(1);
      let connection = &inner.connections[next_connection % inner.connections.len()];
      return futures::future::ok((
        connection.connection.clone(),
        HealthReportToken {
          server_index: connection.server_index,
        },
      ))
      .to_boxed();
    }

    // Unwrap is safe because _some_ server must have an unhealthy_info or we would've already
    // returned it.
    let instant = inner
      .servers
      .iter()
      .filter_map(|server| server.unhealthy_info)
      .map(|info| info.healthy_at())
      .min()
      .unwrap();

    let serverset = self.clone();
    Delay::new(instant)
      .map_err(|err| format!("Error delaying for serverset: {}", err))
      .and_then(move |()| serverset.next())
      .to_boxed()
  }

  pub fn report_health(&self, token: HealthReportToken, health: Health) {
    let mut inner = self.inner.lock();
    let backoff_config = inner.backoff_config;
    let mut unhealthy_info = inner.servers[token.server_index].unhealthy_info.as_mut();
    match health {
      Health::Unhealthy => {
        if unhealthy_info.is_some() {
          if let Some(ref mut unhealthy_info) = unhealthy_info {
            unhealthy_info.increase_backoff(backoff_config);
          }
        } else {
          inner.servers[token.server_index].unhealthy_info =
            Some(UnhealthyInfo::new(inner.backoff_config));
        }

        inner
          .connections
          .retain(|conn| conn.server_index != token.server_index);
      }
      Health::Healthy => {
        if unhealthy_info.is_some() {
          inner.servers[token.server_index].unhealthy_info = unhealthy_info
            .copied()
            .unwrap()
            .decrease_backoff(backoff_config);
        }
      }
    }
  }
}

impl<T: Clone> std::fmt::Debug for Serverset<T> {
  fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> Result<(), std::fmt::Error> {
    let inner = self.inner.lock();
    write!(f, "Serverset {{ {:?} }}", inner.servers)
  }
}

#[cfg(test)]
mod tests {
  use super::{BackoffConfig, Health, Serverset};
  use futures::{self, Future};
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
    runtime.block_on(s.next()).unwrap();

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

  fn expect_both(runtime: &mut tokio::runtime::Runtime, s: &Serverset<String>, repetitions: usize) {
    let visited = Arc::new(Mutex::new(HashSet::new()));

    runtime
      .block_on(futures::future::join_all(
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

  fn mark_bad_as_bad(runtime: &mut tokio::runtime::Runtime, s: &Serverset<String>, health: Health) {
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
}
