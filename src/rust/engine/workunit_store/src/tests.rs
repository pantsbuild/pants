use std::collections::HashSet;
use std::time::Duration;

use crate::{SpanId, WorkunitMetadata, WorkunitStore};

#[test]
fn heavy_hitters_basic() {
  let ws = create_store(vec![], vec![wu_root(0), wu(1, 0)]);
  assert_eq!(vec!["1"], ws.heavy_hitters(1).keys().collect::<Vec<_>>());
}

#[test]
fn straggling_workunits_basic() {
  let ws = create_store(vec![], vec![wu_root(0), wu(1, 0)]);
  assert_eq!(
    vec!["1"],
    ws.straggling_workunits(Duration::from_secs(0))
      .into_iter()
      .map(|(_, n)| n)
      .collect::<Vec<_>>()
  );
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
) -> WorkunitStore {
  let completed_ids = completed
    .iter()
    .map(|(span_id, _)| *span_id)
    .collect::<HashSet<_>>();
  let ws = WorkunitStore::new(true);

  // Start both completed and started workunits.
  let workunits = completed
    .into_iter()
    .chain(started.into_iter())
    .map(|(span_id, parent_id)| {
      ws.start_workunit(
        span_id,
        format!("{}", span_id.0),
        parent_id,
        WorkunitMetadata {
          desc: Some(format!("{}", span_id.0)),
          ..WorkunitMetadata::default()
        },
      )
    })
    .collect::<Vec<_>>();

  // Complete only completed workunits.
  for workunit in workunits {
    if completed_ids.contains(&workunit.span_id) {
      ws.complete_workunit(workunit);
    }
  }

  ws
}

// Used with `create_store` to quickly create a tree of anonymous workunits (with names equal to
// their SpanIds).
type AnonymousWorkunit = (SpanId, Option<SpanId>);

fn wu_root(span_id: u64) -> AnonymousWorkunit {
  (SpanId(span_id), None)
}

fn wu(span_id: u64, parent_id: u64) -> AnonymousWorkunit {
  (SpanId(span_id), Some(SpanId(parent_id)))
}
