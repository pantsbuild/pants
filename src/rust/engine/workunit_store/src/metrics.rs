// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
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

use std::string::ToString;
use strum::IntoEnumIterator;

#[derive(
  Clone,
  Copy,
  PartialEq,
  Eq,
  Hash,
  Debug,
  strum_macros::AsRefStr,
  strum_macros::EnumIter,
  strum_macros::ToString,
)]
#[strum(serialize_all = "snake_case")]
pub enum Metric {
  LocalCacheRequests,
  LocalCacheRequestsCached,
  LocalCacheRequestsUncached,
  LocalCacheReadErrors,
  LocalCacheWriteErrors,
  LocalExecutionRequests,
  RemoteCacheRequests,
  RemoteCacheRequestsCached,
  RemoteCacheRequestsUncached,
  RemoteCacheReadErrors,
  RemoteCacheWriteErrors,
  RemoteCacheWriteStarted,
  RemoteCacheWriteFinished,
  RemoteCacheSpeculationLocalCompletedFirst,
  RemoteCacheSpeculationRemoteCompletedFirst,
  RemoteExecutionErrors,
  RemoteExecutionRequests,
  RemoteExecutionRPCErrors,
  RemoteExecutionRPCExecute,
  RemoteExecutionRPCRetries,
  RemoteExecutionRPCWaitExecution,
  RemoteExecutionSuccess,
  RemoteExecutionTimeouts,
}

impl Metric {
  pub fn all_metrics() -> Vec<String> {
    Metric::iter().map(|variant| variant.to_string()).collect()
  }
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, strum_macros::AsRefStr)]
#[strum(serialize_all = "snake_case")]
pub enum ObservationMetric {
  TestObservation,
  LocalStoreReadBlobSize,
  RemoteExecutionRPCFirstResponseTime,
  RemoteStoreTimeToFirstByte,
}
