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

use deepsize::DeepSizeOf;
use serde_derive::Serialize;

/// A concrete data representation of a duration.
/// Unlike std::time::Duration, it doesn't hide how the time is stored as the purpose of this
/// `struct` is to expose it.
///
/// This type can be serialized with serde.
///
/// This type can be converted from and into a `std::time::Duration` as this should be the goto
/// data representation for a `Duration` when one isn't concerned about serialization.
///
/// It can be used to represent a timestamp (as a duration since the unix epoch) or simply a
/// duration between two arbitrary timestamps.
#[derive(Debug, DeepSizeOf, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
pub struct Duration {
    /// How many seconds did this `Duration` last?
    pub secs: u64,
    /// How many sub-second nanoseconds did this `Duration` last?
    pub nanos: u32,
}

impl Duration {
    /// Construct a new duration with `secs` seconds and `nanos` nanoseconds
    pub fn new(secs: u64, nanos: u32) -> Self {
        Self { secs, nanos }
    }
}

impl From<std::time::Duration> for Duration {
    fn from(duration: std::time::Duration) -> Self {
        Self {
            secs: duration.as_secs(),
            nanos: duration.subsec_nanos(),
        }
    }
}

impl From<Duration> for std::time::Duration {
    fn from(duration: Duration) -> std::time::Duration {
        std::time::Duration::new(duration.secs, duration.nanos)
    }
}

/// A timespan
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
pub struct TimeSpan {
    /// Duration since the UNIX_EPOCH
    pub start: Duration,
    /// Duration since `start`
    pub duration: Duration,
}

impl TimeSpan {
    fn since_epoch(time: &std::time::SystemTime) -> std::time::Duration {
        time.duration_since(std::time::UNIX_EPOCH)
            .expect("Surely you're not before the unix epoch?")
    }

    /// Construct a TimeSpan that started at `start` and ends now.
    pub fn since(start: &std::time::SystemTime) -> TimeSpan {
        let start = Self::since_epoch(start);
        let duration = Self::since_epoch(&std::time::SystemTime::now()) - start;
        TimeSpan {
            start: start.into(),
            duration: duration.into(),
        }
    }

    /// Construct a TimeSpan that started at `start` and ends at `end`.
    pub fn from_start_and_end_systemtime(
        start: &std::time::SystemTime,
        end: &std::time::SystemTime,
    ) -> TimeSpan {
        let start = Self::since_epoch(start);
        let end = Self::since_epoch(end);
        let duration = match end.checked_sub(start) {
            Some(d) => d,
            None => {
                log::debug!("Invalid TimeSpan - start: {:?}, end: {:?}", start, end);
                std::time::Duration::new(0, 0)
            }
        };
        TimeSpan {
            start: start.into(),
            duration: duration.into(),
        }
    }

    fn std_duration_from_timestamp(t: &prost_types::Timestamp) -> std::time::Duration {
        std::time::Duration::new(t.seconds as u64, t.nanos as u32)
    }

    /// Construct a `TimeSpan` given a start and an end `Timestamp` from protobuf timestamp.
    pub fn from_start_and_end(
        start: &prost_types::Timestamp,
        end: &prost_types::Timestamp,
        time_span_description: &str,
    ) -> Result<Self, String> {
        let start = Self::std_duration_from_timestamp(start);
        let end = Self::std_duration_from_timestamp(end);
        match end.checked_sub(start) {
            Some(duration) => Ok(TimeSpan {
                start: start.into(),
                duration: duration.into(),
            }),
            None => Err(format!(
                "Got negative {} time: {:?} - {:?}",
                time_span_description, end, start
            )),
        }
    }
}

#[cfg(test)]
mod tests;
