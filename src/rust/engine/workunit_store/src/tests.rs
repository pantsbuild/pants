use std::collections::HashSet;
use std::sync::atomic;
use std::time::Duration;

use crate::{SpanId, WorkunitMetadata, WorkunitState, WorkunitStore};

#[test]
fn heavy_hitters_basic() {
  let ws = create_store(vec![], vec![wu_root(0), wu(1, 0)], vec![]);
  assert_eq!(vec!["1"], ws.heavy_hitters(1).keys().collect::<Vec<_>>());
}

#[test]
fn straggling_workunits_basic() {
  let ws = create_store(vec![], vec![wu_root(0), wu(1, 0)], vec![]);
  assert_eq!(
    vec!["1"],
    ws.straggling_workunits(Duration::from_secs(0))
      .into_iter()
      .map(|(_, n)| n)
      .collect::<Vec<_>>()
  );
}

#[test]
fn straggling_workunits_blocked() {
  // Test that a blocked leaf is not eligible to be rendered.
  let ws = create_store(vec![], vec![wu_root(0)], vec![wu(1, 0)]);
  assert!(ws.straggling_workunits(Duration::from_secs(0)).is_empty());
}

#[test]
fn workunit_span_id_has_16_digits_len_hex_format() {
  let number: u64 = 1;
  let hex_string = SpanId(number).to_string();
  assert_eq!(16, hex_string.len());
  for ch in hex_string.chars() {
    assert!(ch.is_ascii_hexdigit())
  }
}

#[test]
fn hex_16_digit_string_actually_uses_input_number() {
  assert_eq!(
    SpanId(0x_ffff_ffff_ffff_ffff).to_string(),
    "ffffffffffffffff"
  );
  assert_eq!(SpanId(0x_1).to_string(), "0000000000000001");
  assert_eq!(
    SpanId(0x_0123_4567_89ab_cdef).to_string(),
    "0123456789abcdef"
  );
}

fn create_store(
  completed: Vec<AnonymousWorkunit>,
  started: Vec<AnonymousWorkunit>,
  blocked: Vec<AnonymousWorkunit>,
) -> WorkunitStore {
  let completed_ids = completed
    .iter()
    .map(|(span_id, _, _)| *span_id)
    .collect::<HashSet<_>>();
  let blocked_ids = blocked
    .iter()
    .map(|(span_id, _, _)| *span_id)
    .collect::<HashSet<_>>();
  let ws = WorkunitStore::new(true);

  // Start all of completed, started, and blocked workunits.
  let workunits = completed
    .into_iter()
    .chain(started.into_iter())
    .chain(blocked.into_iter())
    .map(|(span_id, parent_id, metadata)| {
      ws.start_workunit(span_id, format!("{}", span_id.0), parent_id, metadata)
    })
    .collect::<Vec<_>>();

  // Block and blocked workunits, and complete any completed workunits.
  for mut workunit in workunits {
    if blocked_ids.contains(&workunit.span_id) {
      match &mut workunit.state {
        WorkunitState::Started { blocked, .. } => blocked.store(true, atomic::Ordering::Relaxed),
        _ => unreachable!(),
      }
    }
    if completed_ids.contains(&workunit.span_id) {
      ws.complete_workunit(workunit);
    }
  }

  ws
}

// Used with `create_store` to quickly create a tree of anonymous workunits (with names equal to
// their SpanIds).
type AnonymousWorkunit = (SpanId, Option<SpanId>, WorkunitMetadata);

fn wu_root(span_id: u64) -> AnonymousWorkunit {
  wu_meta(span_id, None, WorkunitMetadata::default())
}

fn wu(span_id: u64, parent_id: u64) -> AnonymousWorkunit {
  wu_meta(span_id, Some(parent_id), WorkunitMetadata::default())
}

fn wu_meta(
  span_id: u64,
  parent_id: Option<u64>,
  mut metadata: WorkunitMetadata,
) -> AnonymousWorkunit {
  metadata.desc = Some(format!("{}", span_id));
  (SpanId(span_id), parent_id.map(SpanId), metadata)
}
