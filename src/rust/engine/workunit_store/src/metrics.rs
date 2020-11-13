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

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Metric {
  LocalCacheRequests,
  LocalCacheRequestsCached,
  LocalCacheRequestsUncached,
  LocalCacheReadErrors,
  LocalCacheWriteErrors,
  LocalExecutionRequests,
  RemoteExecutionRequests,
  RemoteExecutionRPCErrors,
  RemoteExecutionRPCExecute,
  RemoteExecutionRPCWaitExecution,
  RemoteExecutionRetries,
  RemoteExecutionTimeouts,
  RemoteCacheRequests,
  RemoteCacheRequestsCached,
  RemoteCacheRequestsUncached,
  RemoteCacheReadErrors,
  RemoteCacheWriteErrors,
}

impl Metric {
  pub fn as_str(&self) -> &'static str {
    use Metric::*;

    match *self {
      LocalCacheRequests => "local_cache_requests",
      LocalCacheRequestsCached => "local_cache_requests_cached",
      LocalCacheRequestsUncached => "local_cache_requests_uncached",
      LocalCacheReadErrors => "local_cache_read_errors",
      LocalCacheWriteErrors => "local_cache_write_errors",
      LocalExecutionRequests => "local_execution_requests",
      RemoteExecutionRequests => "remote_execution_requests",
      RemoteExecutionRetries => "remote_execution_retries",
      RemoteExecutionRPCErrors => "remote_execution_rpc_errors",
      RemoteExecutionRPCExecute => "remote_execution_rpc_execute",
      RemoteExecutionRPCWaitExecution => "remote_execution_rpc_wait_execution",
      RemoteExecutionTimeouts => "remote_execution_timeouts",
      RemoteCacheRequests => "remote_cache_requests",
      RemoteCacheRequestsCached => "remote_cache_requests_cached",
      RemoteCacheRequestsUncached => "remote_cache_requests_uncached",
      RemoteCacheReadErrors => "remote_cache_read_errors",
      RemoteCacheWriteErrors => "remote_cache_write_errors",
    }
  }
}
