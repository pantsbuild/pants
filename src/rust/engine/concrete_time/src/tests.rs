use crate::{Duration, TimeSpan};

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
