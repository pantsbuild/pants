// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashMap;
use std::ffi::CString;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use bytes::{Buf, Bytes};
use hashing::{Digest, Fingerprint};
use lmdb::Transaction;
use parking_lot::Mutex;
use task_executor::Executor;
use tempfile::TempDir;

use crate::{DEFAULT_LEASE_TIME, ShardedLmdb, VersionedFingerprint, lease_from_bytes};

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
    s.store(true, true, Digest::of_bytes(&bytes(0)), || {
        Ok(bytes(0).reader())
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn store_stable() {
    let (s, _tempdir) = new_store(1);
    s.store(true, false, Digest::of_bytes(&bytes(0)), || {
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

    s.store(true, false, Digest::of_bytes(&bytes(2)), move || {
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

#[tokio::test]
async fn overwrite_bytes() {
    let (s, _tempdir) = new_store(1);
    let fingerprint = Digest::of_bytes(&bytes(0)).hash;
    s.store_bytes(fingerprint, bytes(1), false).await.unwrap();

    s.overwrite_bytes(fingerprint, bytes(2)).await.unwrap();

    let stored = s
        .load_bytes_with(fingerprint, |b| Ok(Bytes::copy_from_slice(b)))
        .await
        .unwrap();
    assert_eq!(stored, Some(bytes(2)));
}

#[tokio::test]
async fn stores_on_one_directory_share_environments() {
    let tempdir = TempDir::new().unwrap();
    let first = store_at(tempdir.path());
    let second = store_at(tempdir.path());
    for (id, (_, _, env, _, _)) in &first.lmdbs {
        assert!(Arc::ptr_eq(env, &second.lmdbs[id].2));
    }
}

#[tokio::test]
async fn dropping_one_store_keeps_the_lock_files_locked() {
    let tempdir = TempDir::new().unwrap();
    let first = store_at(tempdir.path());
    let second = store_at(tempdir.path());
    drop(first);
    let shards = shard_dirs(&second);
    assert_eq!(lock_files_locked_by_this_process(&shards), shards.len());
}

#[tokio::test]
async fn dropping_every_store_closes_its_environments() {
    let tempdir = TempDir::new().unwrap();
    let first = store_at(tempdir.path());
    let second = store_at(tempdir.path());
    let shards = shard_dirs(&first);
    drop(first);
    drop(second);
    assert_eq!(lock_files_locked_by_this_process(&shards), 0);
}

#[tokio::test]
async fn a_recreated_directory_gets_new_environments() {
    let tempdir = TempDir::new().unwrap();
    let dir = tempdir.path().join("store");
    let first = store_at(&dir);
    std::fs::remove_dir_all(&dir).unwrap();
    let second = store_at(&dir);
    for (id, (_, _, env, _, _)) in &first.lmdbs {
        assert!(!Arc::ptr_eq(env, &second.lmdbs[id].2));
    }

    let digest = Digest::of_bytes(&bytes(0));
    second
        .store(true, true, digest, || Ok(bytes(0).reader()))
        .await
        .unwrap();
    let loaded = second
        .load_bytes_with(digest.hash, |b| Ok(Bytes::copy_from_slice(b)))
        .await
        .unwrap();
    assert_eq!(loaded, Some(bytes(0)));
}

#[tokio::test]
async fn a_larger_map_size_than_the_open_environment_is_an_error() {
    let tempdir = TempDir::new().unwrap();
    let _open = store_at(tempdir.path());
    let error = open_store(tempdir.path(), 30_000_000).err().unwrap();
    assert!(error.contains("bytes per shard"), "{error}");
}

#[tokio::test]
async fn a_failed_open_closes_the_shards_it_opened() {
    let tempdir = TempDir::new().unwrap();
    std::fs::write(tempdir.path().join("f"), b"").unwrap();
    assert!(open_store(tempdir.path(), 15_000_000).is_err());
    let opened: Vec<PathBuf> = (0..15_u8)
        .map(|b| tempdir.path().join(format!("{b:x}")))
        .collect();
    assert_eq!(lock_files_locked_by_this_process(&opened), 0);
}

#[tokio::test]
async fn a_forked_child_cannot_open_a_store() {
    let tempdir = TempDir::new().unwrap();
    let _parent = store_at(tempdir.path());
    match unsafe { libc::fork() } {
        0 => {
            let refused = std::panic::catch_unwind(|| {
                open_store(tempdir.path(), 15_000_000)
                    .is_err_and(|e| e.contains("forked from one that has opened a store"))
            });
            unsafe { libc::_exit(if matches!(refused, Ok(true)) { 0 } else { 1 }) }
        }
        child => {
            assert!(child > 0, "fork failed");
            let mut status = 0;
            assert_eq!(unsafe { libc::waitpid(child, &mut status, 0) }, child);
            assert!(
                libc::WIFEXITED(status) && libc::WEXITSTATUS(status) == 0,
                "the child opened a store: wait status {status}"
            );
        }
    }
}

fn store_at(dir: &Path) -> ShardedLmdb {
    open_store(dir, 15_000_000).unwrap()
}

fn open_store(dir: &Path, max_size: usize) -> Result<ShardedLmdb, String> {
    ShardedLmdb::new(
        dir.to_owned(),
        max_size,
        Executor::new(),
        DEFAULT_LEASE_TIME,
        16,
    )
}

fn shard_dirs(store: &ShardedLmdb) -> Vec<PathBuf> {
    store
        .lmdbs
        .values()
        .map(|(_, dir, _, _, _)| dir.clone())
        .collect()
}

/// Counts the shards whose `lock.mdb` this process holds a lock on. `F_GETLK` never reports the
/// caller's own locks, so a forked child checks, using only async-signal-safe calls.
#[allow(clippy::unnecessary_cast)]
fn lock_files_locked_by_this_process(shard_dirs: &[PathBuf]) -> usize {
    const CHECK_FAILED: i32 = 255;
    let lock_files: Vec<CString> = shard_dirs
        .iter()
        .map(|dir| CString::new(dir.join("lock.mdb").as_os_str().as_bytes()).unwrap())
        .collect();
    let parent = unsafe { libc::getpid() };
    match unsafe { libc::fork() } {
        0 => {
            let mut locked = 0;
            for lock_file in &lock_files {
                let fd = unsafe { libc::open(lock_file.as_ptr(), libc::O_RDWR) };
                let mut lock: libc::flock = unsafe { std::mem::zeroed() };
                lock.l_type = libc::F_WRLCK as libc::c_short;
                lock.l_whence = libc::SEEK_SET as libc::c_short;
                lock.l_start = 0;
                lock.l_len = 1;
                if fd < 0
                    || unsafe { libc::fcntl(fd, libc::F_GETLK, &mut lock as *mut libc::flock) } != 0
                {
                    unsafe { libc::_exit(CHECK_FAILED) }
                }
                if lock.l_type != libc::F_UNLCK as libc::c_short && lock.l_pid == parent {
                    locked += 1;
                }
            }
            unsafe { libc::_exit(locked) }
        }
        child => {
            assert!(child > 0, "fork failed");
            let mut status = 0;
            assert_eq!(unsafe { libc::waitpid(child, &mut status, 0) }, child);
            assert!(
                libc::WIFEXITED(status) && libc::WEXITSTATUS(status) != CHECK_FAILED,
                "the lock check failed: wait status {status}"
            );
            libc::WEXITSTATUS(status) as usize
        }
    }
}

fn bytes(content: u8) -> Bytes {
    Bytes::from(vec![content; 100])
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}

fn versioned(fingerprint: Fingerprint) -> VersionedFingerprint {
    VersionedFingerprint::new(fingerprint, ShardedLmdb::SCHEMA_VERSION)
}

fn set_lease(s: &ShardedLmdb, fingerprint: Fingerprint, until_secs_since_epoch: u64) {
    let (env, _, lease_database) = s.get(&fingerprint);
    let mut txn = env.begin_rw_txn().unwrap();
    s.lease_inner(
        lease_database,
        &versioned(fingerprint),
        until_secs_since_epoch,
        &mut txn,
    )
    .unwrap();
    txn.commit().unwrap();
}

fn stored_lease(s: &ShardedLmdb, fingerprint: Fingerprint) -> u64 {
    let (env, _, lease_database) = s.get(&fingerprint);
    let txn = env.begin_ro_txn().unwrap();
    lease_from_bytes(
        txn.get(lease_database, &versioned(fingerprint).as_ref())
            .unwrap(),
    )
}

#[tokio::test]
async fn lease_creates_missing_lease() {
    let (s, _tempdir) = new_store(1);
    let fingerprint = Digest::of_bytes(&bytes(0)).hash;

    let before = now_secs();
    s.lease(fingerprint).await.unwrap();

    assert!(stored_lease(&s, fingerprint) >= before + DEFAULT_LEASE_TIME.as_secs());
}

#[tokio::test]
async fn lease_renews_lease_with_less_than_half_left() {
    let (s, _tempdir) = new_store(1);
    let fingerprint = Digest::of_bytes(&bytes(0)).hash;
    set_lease(
        &s,
        fingerprint,
        now_secs() + DEFAULT_LEASE_TIME.as_secs() / 2 - 60,
    );

    let before = now_secs();
    s.lease(fingerprint).await.unwrap();

    assert!(stored_lease(&s, fingerprint) >= before + DEFAULT_LEASE_TIME.as_secs());
}

#[tokio::test]
async fn lease_keeps_lease_with_more_than_half_left() {
    let (s, _tempdir) = new_store(1);
    let fingerprint = Digest::of_bytes(&bytes(0)).hash;
    let until = now_secs() + DEFAULT_LEASE_TIME.as_secs() / 2 + 60;
    set_lease(&s, fingerprint, until);

    s.lease(fingerprint).await.unwrap();

    assert_eq!(stored_lease(&s, fingerprint), until);
}

#[tokio::test]
async fn store_bytes_batch_renewing_leases_creates_missing_lease() {
    let (s, _tempdir) = new_store(1);
    let fingerprint = Digest::of_bytes(&bytes(0)).hash;
    s.store_bytes(fingerprint, bytes(0), false).await.unwrap();

    let before = now_secs();
    s.store_bytes_batch_renewing_leases(vec![(fingerprint, bytes(0))])
        .await
        .unwrap();

    assert!(stored_lease(&s, fingerprint) >= before + DEFAULT_LEASE_TIME.as_secs());
}

#[tokio::test]
async fn store_bytes_batch_renewing_leases_renews_lease_with_less_than_half_left() {
    let (s, _tempdir) = new_store(1);
    let fingerprint = Digest::of_bytes(&bytes(0)).hash;
    s.store_bytes(fingerprint, bytes(0), true).await.unwrap();
    set_lease(
        &s,
        fingerprint,
        now_secs() + DEFAULT_LEASE_TIME.as_secs() / 2 - 60,
    );

    let before = now_secs();
    s.store_bytes_batch_renewing_leases(vec![(fingerprint, bytes(0))])
        .await
        .unwrap();

    assert!(stored_lease(&s, fingerprint) >= before + DEFAULT_LEASE_TIME.as_secs());
}

#[tokio::test]
async fn store_bytes_batch_renewing_leases_keeps_lease_with_more_than_half_left() {
    let (s, _tempdir) = new_store(1);
    let fingerprint = Digest::of_bytes(&bytes(0)).hash;
    s.store_bytes(fingerprint, bytes(0), true).await.unwrap();
    let until = now_secs() + DEFAULT_LEASE_TIME.as_secs() / 2 + 60;
    set_lease(&s, fingerprint, until);

    s.store_bytes_batch_renewing_leases(vec![(fingerprint, bytes(0))])
        .await
        .unwrap();

    assert_eq!(stored_lease(&s, fingerprint), until);
}

#[tokio::test]
async fn store_bytes_batch_keeps_lease_with_less_than_half_left() {
    let (s, _tempdir) = new_store(1);
    let fingerprint = Digest::of_bytes(&bytes(0)).hash;
    s.store_bytes(fingerprint, bytes(0), true).await.unwrap();
    let until = now_secs() + DEFAULT_LEASE_TIME.as_secs() / 2 - 60;
    set_lease(&s, fingerprint, until);

    s.store_bytes(fingerprint, bytes(0), true).await.unwrap();

    assert_eq!(stored_lease(&s, fingerprint), until);
}
