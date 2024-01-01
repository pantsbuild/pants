// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashMap;

use bytes::{Buf, Bytes};
use hashing::Digest;
use parking_lot::Mutex;
use task_executor::Executor;
use tempfile::TempDir;

use crate::{ShardedLmdb, DEFAULT_LEASE_TIME};

fn new_store(shard_count: u8) -> (ShardedLmdb, TempDir) {
    let tempdir = TempDir::new().unwrap();
    let s = ShardedLmdb::new(
        tempdir.path().to_owned(),
        15_000_000,
        Executor::new(),
        DEFAULT_LEASE_TIME,
        shard_count,
    )
    .unwrap();
    (s, tempdir)
}

#[tokio::test]
async fn shard_counts() {
    let shard_counts = vec![1, 2, 4, 8, 16, 32, 64, 128];
    for shard_count in shard_counts {
        let (s, _tempdir) = new_store(shard_count);
        assert_eq!(s.all_lmdbs().len(), shard_count as usize);

        // Confirm that each database gets an even share.
        let mut databases = HashMap::new();
        for prefix_byte in 0_u8..=255_u8 {
            *databases.entry(s.get_raw(&[prefix_byte]).0).or_insert(0) += 1;
        }
        assert_eq!(databases.len(), shard_count as usize);
        for (_, count) in databases {
            assert_eq!(count, 256 / shard_count as usize);
        }
    }
}

#[tokio::test]
async fn store_immutable() {
    let (s, _tempdir) = new_store(1);
    s
        .store(true, true, Digest::of_bytes(&bytes(0)), || {
            Ok(bytes(0).reader())
        })
        .await
        .unwrap();
}

#[tokio::test]
async fn store_stable() {
    let (s, _tempdir) = new_store(1);
    s
        .store(true, false, Digest::of_bytes(&bytes(0)), || {
            Ok(bytes(0).reader())
        })
        .await
        .unwrap();
}

#[tokio::test]
async fn store_changing() {
    let (s, _tempdir) = new_store(1);

    // Produces Readers that change during the first two reads, but stabilize on the third and
    // fourth.
    let contents = Mutex::new(vec![bytes(0), bytes(1), bytes(2), bytes(2)].into_iter());

    s
        .store(true, false, Digest::of_bytes(&bytes(2)), move || {
            Ok(contents.lock().next().unwrap().reader())
        })
        .await
        .unwrap();
}

#[tokio::test]
async fn store_failure() {
    let (s, _tempdir) = new_store(1);

    // Produces Readers that never stabilize.
    let contents = Mutex::new((0..100).map(bytes));

    let result = s
        .store(true, false, Digest::of_bytes(&bytes(101)), move || {
            Ok(contents.lock().next().unwrap().reader())
        })
        .await;
    assert!(result.is_err());
}

fn bytes(content: u8) -> Bytes {
    Bytes::from(vec![content; 100])
}
