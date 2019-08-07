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
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
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

impl Into<std::time::Duration> for Duration {
  fn into(self) -> std::time::Duration {
    std::time::Duration::new(self.secs, self.nanos)
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
    time
      .duration_since(std::time::UNIX_EPOCH)
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

  fn std_duration_from_protobuf_timestamp(
    t: &protobuf::well_known_types::Timestamp,
  ) -> std::time::Duration {
    std::time::Duration::new(t.seconds as u64, t.nanos as u32)
  }

  /// Construct a `TimeSpan` given a start and an end `Timestamp` from protobuf
  pub fn from_start_and_end(
    start: &protobuf::well_known_types::Timestamp,
    end: &protobuf::well_known_types::Timestamp,
    time_span_description: &str,
  ) -> Result<Self, String> {
    let start = Self::std_duration_from_protobuf_timestamp(start);
    let end = Self::std_duration_from_protobuf_timestamp(end);
    let time_span = end.checked_sub(start).map(|duration| TimeSpan {
      start: start.into(),
      duration: duration.into(),
    });
    time_span.ok_or_else(|| {
      format!(
        "Got negative {} time: {:?} - {:?}",
        time_span_description, end, start
      )
    })
  }
}

#[cfg(test)]
mod tests {
  use super::{Duration, TimeSpan};
  #[test]
  fn convert_from_std_duration() {
    let std = std::time::Duration::new(3, 141_592_653);
    let concrete: Duration = std.into();
    assert_eq!(std.as_secs(), concrete.secs);
    assert_eq!(std.subsec_nanos(), concrete.nanos);
  }

  #[test]
  fn convert_into_std_duration() {
    let concrete = Duration::new(3, 141_592_653);
    let std: std::time::Duration = concrete.into();
    assert_eq!(concrete.secs, std.as_secs());
    assert_eq!(concrete.nanos, std.subsec_nanos());
  }

  #[test]
  fn time_span_since() {
    let start = std::time::SystemTime::now();
    let sleep_duration = std::time::Duration::from_millis(1);
    std::thread::sleep(sleep_duration);
    let span = TimeSpan::since(&start);
    assert!(std::convert::Into::<std::time::Duration>::into(span.duration) >= sleep_duration);
    assert_eq!(
      start
        .duration_since(std::time::SystemTime::UNIX_EPOCH)
        .unwrap(),
      span.start.into()
    );
  }

  fn time_span_from_start_and_duration_in_seconds(
    start: i64,
    duration: i64,
  ) -> Result<TimeSpan, String> {
    use protobuf::well_known_types::Timestamp;
    let mut start_timestamp = Timestamp::new();
    start_timestamp.set_seconds(start);
    let mut end_timestamp = Timestamp::new();
    end_timestamp.set_seconds(start + duration);
    TimeSpan::from_start_and_end(&start_timestamp, &end_timestamp, "")
  }

  #[test]
  fn time_span_from_start_and_end_given_positive_duration() {
    let span = time_span_from_start_and_duration_in_seconds(42, 10);
    assert_eq!(
      Ok(TimeSpan {
        start: Duration::new(42, 0),
        duration: Duration::new(10, 0),
      }),
      span
    );
  }

  #[test]
  fn time_span_from_start_and_end_given_negative_duration() {
    let span = time_span_from_start_and_duration_in_seconds(42, -10);
    assert!(span.is_err());
  }
}
