// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashSet;
use std::sync::atomic;
use std::time::Duration;

use internment::Intern;

use crate::{Level, ParentIds, SpanId, WorkunitMetadata, WorkunitState, WorkunitStore};

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
async fn disabled_workunit_is_filtered() {
    // Create a chain of completed workunits like: Info -> Trace -> Info (where `Trace` is below the
    // minimum level recoded in the store).
    let ws = create_store(
        vec![],
        vec![],
        vec![
            wu_level(0, None, Level::Info),
            wu_level(1, Some(0), Level::Trace),
            wu_level(2, Some(1), Level::Info),
        ],
    );

    // Confirm that latest_workunits reports the two Info level workunits while fixing up parent links.
    let (_, completed) = ws.latest_workunits(Level::Info);
    assert_eq!(completed.len(), 2);
    assert_eq!(completed[0].parent_ids, ParentIds::new());
    assert_eq!(
        completed[1].parent_ids,
        vec![SpanId(0)].into_iter().collect::<ParentIds>()
    );
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

                // Then return new metadata and raise the workunit's level.
                Some((
                    WorkunitMetadata {
                        desc: Some(new_desc.to_owned()),
                        ..WorkunitMetadata::default()
                    },
                    Level::Info,
                ))
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
    assert_eq!(SpanId(0x0001).to_string(), "0000000000000001");
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
        .map(|(_, span_id, _, _)| *span_id)
        .collect::<HashSet<_>>();
    let blocked_ids = blocked
        .iter()
        .map(|(_, span_id, _, _)| *span_id)
        .collect::<HashSet<_>>();
    let ws = WorkunitStore::new(true, log::Level::Debug);

    // Collect and sort by SpanId.
    let mut all = started
        .into_iter()
        .chain(blocked)
        .chain(completed)
        .collect::<Vec<_>>();
    all.sort_by(|a, b| a.1.cmp(&b.1));

    // Start all workunits in SpanId order.
    let workunits = all
        .into_iter()
        .map(|(level, span_id, parent_id, metadata)| {
            if let Some(parent_id) = parent_id {
                assert!(span_id > parent_id);
            }
            ws._start_workunit(
                span_id,
                Intern::new(format!("{}", span_id.0)).as_ref(),
                level,
                parent_id,
                Some(metadata),
            )
        })
        .collect::<Vec<_>>();

    // Block and blocked workunits, and complete any completed workunits.
    for mut workunit in workunits {
        if blocked_ids.contains(&workunit.span_id) {
            match &mut workunit.state {
                WorkunitState::Started { blocked, .. } => {
                    blocked.store(true, atomic::Ordering::Relaxed)
                }
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
type AnonymousWorkunit = (Level, SpanId, Option<SpanId>, WorkunitMetadata);

fn wu_root(span_id: u64) -> AnonymousWorkunit {
    wu_level(span_id, None, Level::Info)
}

fn wu(span_id: u64, parent_id: u64) -> AnonymousWorkunit {
    wu_level(span_id, Some(parent_id), Level::Info)
}

fn wu_level(span_id: u64, parent_id: Option<u64>, level: Level) -> AnonymousWorkunit {
    let mut metadata = WorkunitMetadata::default();
    metadata.desc = Some(format!("{span_id}"));
    (level, SpanId(span_id), parent_id.map(SpanId), metadata)
}
