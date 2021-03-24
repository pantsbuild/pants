use std::collections::HashMap;

use task_executor::Executor;
use tempfile::TempDir;

use crate::{ShardedLmdb, DEFAULT_LEASE_TIME};

fn new_store(shard_count: u8) -> (ShardedLmdb, TempDir) {
  let tempdir = TempDir::new().unwrap();
  let s = ShardedLmdb::new(
    tempdir.path().to_owned(),
    10_000_000,
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
    let (s, _) = new_store(shard_count);
    assert_eq!(s.all_lmdbs().len(), shard_count as usize);

    // Confirm that each database gets an even share.
    let mut databases = HashMap::new();
    for prefix_byte in 0u8..=255u8 {
      *databases
        .entry(s.get_raw(prefix_byte).0.clone())
        .or_insert(0) += 1;
    }
    assert_eq!(databases.len(), shard_count as usize);
    for (_, count) in databases {
      assert_eq!(count, 256 / shard_count as usize);
    }
  }
}
