use std::collections::HashSet;
use std::sync::atomic;
use std::time::Duration;

use internment::Intern;

use crate::{Level, SpanId, WorkunitMetadata, WorkunitState, WorkunitStore};

#[test]
fn heavy_hitters_basic() {
  let ws = create_store(vec![wu_root(0), wu(1, 0)], vec![], vec![]);
  assert_eq!(
    vec![SpanId(1)],
    ws.heavy_hitters(1).keys().cloned().collect::<Vec<_>>()
  );
}

#[test]
fn heavy_hitters_only_running() {
  // A completed child should not prevent a parent from being rendered.
  let ws = create_store(vec![wu_root(0), wu(1, 0)], vec![], vec![wu(2, 1)]);
  assert_eq!(
    vec![SpanId(1)],
    ws.heavy_hitters(1).keys().cloned().collect::<Vec<_>>()
  );
}

#[test]
fn heavy_hitters_blocked_path() {
  // Test that a chain of blocked workunits do not cause their parents to be rendered.
  let ws = create_store(vec![wu_root(0)], vec![wu(1, 0), wu(2, 1)], vec![]);
  assert!(ws.heavy_hitters(1).is_empty());
}

#[test]
fn straggling_workunits_basic() {
  let ws = create_store(vec![wu_root(0), wu(1, 0)], vec![], vec![]);
  assert_eq!(
    vec!["1"],
    ws.straggling_workunits(Duration::from_secs(0))
      .into_iter()
      .map(|(_, n)| n)
      .collect::<Vec<_>>()
  );
}

#[test]
fn straggling_workunits_blocked_leaf() {
  // Test that a blocked leaf does not cause its parents to be rendered.
  let ws = create_store(vec![wu_root(0)], vec![wu(1, 0)], vec![]);
  assert!(ws.straggling_workunits(Duration::from_secs(0)).is_empty());
}

#[test]
fn straggling_workunits_blocked_path() {
  // Test that a chain of blocked workunits do not cause their parents to be rendered.
  let ws = create_store(vec![wu_root(0)], vec![wu(1, 0), wu(2, 1)], vec![]);
  assert!(ws.straggling_workunits(Duration::from_secs(0)).is_empty());
}

#[tokio::test]
async fn workunit_escalation_is_recorded() {
  // Create a store which will disable Debug level workunits.
  let ws = WorkunitStore::new(true, Level::Info);
  ws.init_thread_state(None);

  // Start a workunit at Debug (below the level of the store).
  let new_desc = "One more thing!";
  in_workunit!(
    "super_fine",
    Level::Debug,
    desc = Some("Should be ignored".to_owned()),
    |workunit| async move {
      workunit.update_metadata(|metadata| {
        // Ensure that it has no metadata (i.e.: is disabled).
        assert!(metadata.is_none());

        // Then return new metadata to raise the workunit's level.
        Some(WorkunitMetadata {
          level: Level::Info,
          desc: Some(new_desc.to_owned()),
          ..WorkunitMetadata::default()
        })
      });
    }
  )
  .await;

  // Finally, confirm that the workunit did end up recorded using the new level.
  let (started, completed) = ws.latest_workunits(Level::Info);
  assert!(started.is_empty());
  assert_eq!(
    completed
      .into_iter()
      .map(|wu| wu.metadata.and_then(|m| m.desc))
      .collect::<Vec<_>>(),
    vec![Some(new_desc.to_owned())]
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
  started: Vec<AnonymousWorkunit>,
  blocked: Vec<AnonymousWorkunit>,
  completed: Vec<AnonymousWorkunit>,
) -> WorkunitStore {
  let completed_ids = completed
    .iter()
    .map(|(span_id, _, _)| *span_id)
    .collect::<HashSet<_>>();
  let blocked_ids = blocked
    .iter()
    .map(|(span_id, _, _)| *span_id)
    .collect::<HashSet<_>>();
  let ws = WorkunitStore::new(true, log::Level::Debug);

  // Collect and sort by SpanId.
  let mut all = started
    .into_iter()
    .chain(blocked.into_iter())
    .chain(completed.into_iter())
    .collect::<Vec<_>>();
  all.sort_by(|a, b| a.0.cmp(&b.0));

  // Start all workunits in SpanId order.
  let workunits = all
    .into_iter()
    .map(|(span_id, parent_id, metadata)| {
      if let Some(parent_id) = parent_id {
        assert!(span_id > parent_id);
      }
      ws._start_workunit(
        span_id,
        Intern::new(format!("{}", span_id.0)).as_ref(),
        parent_id,
        Some(metadata),
      )
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
