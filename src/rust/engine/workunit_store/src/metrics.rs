// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::string::ToString;
use strum::IntoEnumIterator;

#[derive(
    Clone,
    Copy,
    PartialEq,
    Eq,
    Hash,
    Debug,
    strum_macros::IntoStaticStr,
    strum_macros::EnumIter,
    strum_macros::Display,
)]
#[strum(serialize_all = "snake_case")]
pub enum Metric {
    LocalProcessTotalTimeRunMs,
    LocalCacheRequests,
    LocalCacheRequestsCached,
    LocalCacheRequestsUncached,
    LocalCacheReadErrors,
    LocalCacheWriteErrors,
    /// The total time saved (in milliseconds) thanks to local cache hits instead of running the
    /// processes directly.
    LocalCacheTotalTimeSavedMs,
    LocalExecutionRequests,
    RemoteProcessTotalTimeRunMs,
    RemoteCacheRequests,
    RemoteCacheRequestsCached,
    RemoteCacheRequestsUncached,
    RemoteCacheReadErrors,
    RemoteCacheWriteAttempts,
    RemoteCacheWriteSuccesses,
    RemoteCacheWriteErrors,
    RemoteCacheSpeculationLocalCompletedFirst,
    RemoteCacheSpeculationRemoteCompletedFirst,
    /// The total time saved (in milliseconds) thanks to remote cache hits instead of running the
    /// processes directly.
    RemoteCacheTotalTimeSavedMs,
    RemoteExecutionErrors,
    RemoteExecutionRequests,
    RemoteExecutionRPCErrors,
    RemoteExecutionRPCExecute,
    RemoteExecutionRPCRetries,
    RemoteExecutionRPCWaitExecution,
    RemoteExecutionSuccess,
    RemoteExecutionTimeouts,
    RemoteStoreMissingDigest,
    /// Number of times that we backtracked due to missing digests.
    BacktrackAttempts,
}

impl Metric {
    pub fn all_metrics() -> Vec<String> {
        Metric::iter().map(|variant| variant.to_string()).collect()
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, strum_macros::IntoStaticStr)]
#[strum(serialize_all = "snake_case")]
pub enum ObservationMetric {
    TestObservation,
    LocalProcessTimeRunMs,
    LocalStoreReadBlobSize,
    LocalStoreReadBlobTimeMicros,
    RemoteProcessTimeRunMs,
    RemoteExecutionRPCFirstResponseTimeMicros,
    RemoteStoreTimeToFirstByteMicros,
    RemoteStoreReadBlobTimeMicros,
    /// Total number of bytes of blobs downloaded from a remote CAS.
    RemoteStoreBlobBytesDownloaded,
    /// Total number of bytes of blobs uploaded to a remote CAS.
    RemoteStoreBlobBytesUploaded,
    /// The time saved (in milliseconds) thanks to a local cache hit instead of running the process
    /// directly.
    LocalCacheTimeSavedMs,
    /// The time saved (in milliseconds) thanks to a remote cache hit instead of running the process
    /// directly.
    RemoteCacheTimeSavedMs,
    /// Remote cache timing (in microseconds) for GetActionResult calls. Includes client-side
    /// queuing due to concurrency limits.
    RemoteCacheGetActionResultTimeMicros,
    /// Remote cache timing (in microseconds) for GetActionResult calls (network timing only).
    RemoteCacheGetActionResultNetworkTimeMicros,
}
