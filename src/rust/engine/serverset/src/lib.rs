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
  clippy::unseparated_literal_suffix,
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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

use futures::future::{BoxFuture, FutureExt};
use parking_lot::Mutex;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::time::delay_until;

pub mod retry;

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
  // Order and size is immutable through the lifetime of a Serverset, but contents of the Backend
  // may change. This in particular means that it's ok for a Connection to point at an index in this
  // Vec.
  servers: Vec<Backend>,
  // Only visible for testing
  // When a new connection is desired, this (mod servers.len()) points at the index into servers
  // where we will start trying to make connections.
  pub(crate) next_server: usize,

  // Points into the servers list; may change over time. Nothing should hold indexes into this Vec
  // (except `next_connection` which refers to an order rather than a particular Connection).
  connections: Vec<Connection<T>>,
  // When an existing connection is to be re-used, this (mod connections.len()) points at which
  // connection will be used.
  next_connection: usize,

  connect: Box<dyn Fn(&str) -> T + 'static + Send>,

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

#[derive(Clone, Copy, Debug)]
struct UnhealthyInfo {
  unhealthy_since: Instant,
  next_attempt_after: Duration,
}

impl UnhealthyInfo {
  fn new(backoff_config: BackoffConfig) -> UnhealthyInfo {
    UnhealthyInfo {
      unhealthy_since: Instant::now(),
      next_attempt_after: backoff_config.initial_lame,
    }
  }

  fn healthy_at(&self) -> Instant {
    self.unhealthy_since + self.next_attempt_after
  }

  fn increase_backoff(&mut self, backoff_config: BackoffConfig) {
    self.unhealthy_since = Instant::now();
    self.next_attempt_after = Duration::from_secs_f64(f64::min(
      backoff_config.max_lame.as_secs_f64(),
      self.next_attempt_after.as_secs_f64() * backoff_config.ratio,
    ));
  }

  fn decrease_backoff(mut self, backoff_config: BackoffConfig) -> Option<UnhealthyInfo> {
    self.unhealthy_since = Instant::now();
    let next_value = self.next_attempt_after.as_secs_f64() / backoff_config.ratio;
    if next_value < backoff_config.initial_lame.as_secs_f64() {
      None
    } else {
      self.next_attempt_after = Duration::from_secs_f64(next_value);
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

#[derive(Clone, Copy, Debug)]
pub struct BackoffConfig {
  ///
  /// The time a backend will be skipped after it is first reported unhealthy.
  ///
  initial_lame: Duration,

  ///
  /// Ratio by which to multiply the most recent lame duration if a backend continues to be
  /// unhealthy.
  ///
  /// The inverse is used when easing back in after health recovery.
  ratio: f64,

  ///
  /// Maximum duration to wait between attempts.
  ///
  max_lame: Duration,
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

    Ok(BackoffConfig {
      initial_lame,
      ratio,
      max_lame,
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
  /// This aims to roughly load-balance between a number of open connections to servers, but does
  /// not guarantee to do so perfectly. In particular, whenever a connection is opened or closed,
  /// we are likely to re-order slightly.
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
  pub fn next(&self) -> BoxFuture<Result<(T, HealthReportToken), String>> {
    let serverset = self.clone();
    async move {
      let instant = {
        let mut inner = serverset.inner.lock();

        if inner.can_make_more_connections() {
          // Find a healthy server without a connection, connect to it.
          if let Some(ret) = inner.connect() {
            return Ok(ret);
          }
        }

        if !inner.connections.is_empty() {
          let next_connection = inner.next_connection;
          inner.next_connection = inner.next_connection.wrapping_add(1);
          let connection = &inner.connections[next_connection % inner.connections.len()];
          return Ok((
            connection.connection.clone(),
            HealthReportToken {
              server_index: connection.server_index,
            },
          ));
        }

        // Unwrap is safe because _some_ server must have an unhealthy_info or we would've already
        // returned it.
        inner
          .servers
          .iter()
          .filter_map(|server| server.unhealthy_info)
          .map(|info| info.healthy_at())
          .min()
          .unwrap()
      };

      delay_until(instant.into()).await;
      serverset.next().await
    }
    .boxed()
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
mod tests;

#[cfg(test)]
mod retry_tests;
