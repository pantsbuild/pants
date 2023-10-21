// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use super::{EntryType, ShrinkBehavior};

use std::collections::{BinaryHeap, HashSet};
use std::fmt::Debug;
use std::io::{self, Read};
use std::path::Path;
use std::sync::Arc;
use std::time::{self, Duration, Instant};

use bytes::Bytes;
use futures::future;
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use lmdb::Error::NotFound;
use lmdb::{self, Cursor, Transaction};
use sharded_lmdb::{ShardedLmdb, VersionedFingerprint};
use workunit_store::ObservationMetric;

#[derive(Debug, Clone)]
pub struct ByteStore {
    inner: Arc<InnerStore>,
}

#[derive(Debug)]
struct InnerStore {
    // Store directories separately from files because:
    //  1. They may have different lifetimes.
    //  2. It's nice to know whether we should be able to parse something as a proto.
    file_dbs: Result<Arc<ShardedLmdb>, String>,
    directory_dbs: Result<Arc<ShardedLmdb>, String>,
    executor: task_executor::Executor,
}

impl ByteStore {
    pub fn new<P: AsRef<Path>>(
        executor: task_executor::Executor,
        path: P,
    ) -> Result<ByteStore, String> {
        Self::new_with_options(executor, path, super::LocalOptions::default())
    }

    pub fn new_with_options<P: AsRef<Path>>(
        executor: task_executor::Executor,
        path: P,
        options: super::LocalOptions,
    ) -> Result<ByteStore, String> {
        let root = path.as_ref();
        let files_root = root.join("files");
        let directories_root = root.join("directories");
        Ok(ByteStore {
            inner: Arc::new(InnerStore {
                file_dbs: ShardedLmdb::new(
                    files_root,
                    options.files_max_size_bytes,
                    executor.clone(),
                    options.lease_time,
                    options.shard_count,
                )
                .map(Arc::new),
                directory_dbs: ShardedLmdb::new(
                    directories_root,
                    options.directories_max_size_bytes,
                    executor.clone(),
                    options.lease_time,
                    options.shard_count,
                )
                .map(Arc::new),
                executor,
            }),
        })
    }

    pub fn executor(&self) -> &task_executor::Executor {
        &self.inner.executor
    }

    pub async fn entry_type(&self, fingerprint: Fingerprint) -> Result<Option<EntryType>, String> {
        if fingerprint == EMPTY_DIGEST.hash {
            // Technically this is valid as both; choose Directory in case a caller is checking whether
            // it _can_ be a Directory.
            return Ok(Some(EntryType::Directory));
        }

        // In parallel, check for the given fingerprint in both databases.
        let d_dbs = self.inner.directory_dbs.clone()?;
        let is_dir = d_dbs.exists(fingerprint);
        let f_dbs = self.inner.file_dbs.clone()?;
        let is_file = f_dbs.exists(fingerprint);

        // TODO: Could technically use select to return slightly more quickly with the first
        // affirmative answer, but this is simpler.
        match future::try_join(is_dir, is_file).await? {
            (true, _) => Ok(Some(EntryType::Directory)),
            (_, true) => Ok(Some(EntryType::File)),
            (false, false) => Ok(None),
        }
    }

    pub async fn lease_all(
        &self,
        digests: impl Iterator<Item = (Digest, EntryType)>,
    ) -> Result<(), String> {
        // NB: Lease extension happens periodically in the background, so this code needn't be parallel.
        for (digest, entry_type) in digests {
            let dbs = match entry_type {
                EntryType::File => self.inner.file_dbs.clone(),
                EntryType::Directory => self.inner.directory_dbs.clone(),
            };
            dbs?.lease(digest.hash)
                .await
                .map_err(|err| format!("Error leasing digest {digest:?}: {err}"))?;
        }
        Ok(())
    }

    ///
    /// Attempts to shrink the stored files to be no bigger than target_bytes
    /// (excluding lmdb overhead).
    ///
    /// Returns the size it was shrunk to, which may be larger than target_bytes.
    ///
    /// TODO: Use LMDB database statistics when lmdb-rs exposes them.
    ///
    pub fn shrink(
        &self,
        target_bytes: usize,
        shrink_behavior: ShrinkBehavior,
    ) -> Result<usize, String> {
        let mut used_bytes: usize = 0;
        let mut fingerprints_by_expired_ago = BinaryHeap::new();

        self.aged_fingerprints(
            EntryType::File,
            &mut used_bytes,
            &mut fingerprints_by_expired_ago,
        )?;
        self.aged_fingerprints(
            EntryType::Directory,
            &mut used_bytes,
            &mut fingerprints_by_expired_ago,
        )?;
        while used_bytes > target_bytes {
            let aged_fingerprint = fingerprints_by_expired_ago
                .pop()
                .expect("lmdb corruption detected, sum of size of blobs exceeded stored blobs");
            if aged_fingerprint.expired_seconds_ago == 0 {
                // Ran out of expired blobs - everything remaining is leased and cannot be collected.
                return Ok(used_bytes);
            }
            let lmdbs = match aged_fingerprint.entry_type {
                EntryType::File => self.inner.file_dbs.clone(),
                EntryType::Directory => self.inner.directory_dbs.clone(),
            };
            let (env, database, lease_database) = lmdbs.clone()?.get(&aged_fingerprint.fingerprint);
            {
                env.begin_rw_txn()
                    .and_then(|mut txn| {
                        let key = VersionedFingerprint::new(
                            aged_fingerprint.fingerprint,
                            ShardedLmdb::SCHEMA_VERSION,
                        );
                        txn.del(database, &key, None)?;

                        txn.del(lease_database, &key, None)
                            .or_else(|err| match err {
                                NotFound => Ok(()),
                                err => Err(err),
                            })?;
                        used_bytes -= aged_fingerprint.size_bytes;
                        txn.commit()
                    })
                    .map_err(|err| format!("Error garbage collecting: {err}"))?;
            }
        }

        if shrink_behavior == ShrinkBehavior::Compact {
            self.inner.file_dbs.clone()?.compact()?;
        }

        Ok(used_bytes)
    }

    fn aged_fingerprints(
        &self,
        entry_type: EntryType,
        used_bytes: &mut usize,
        fingerprints_by_expired_ago: &mut BinaryHeap<AgedFingerprint>,
    ) -> Result<(), String> {
        let database = match entry_type {
            EntryType::File => self.inner.file_dbs.clone(),
            EntryType::Directory => self.inner.directory_dbs.clone(),
        };

        for (env, database, lease_database) in &database?.all_lmdbs() {
            let txn = env
                .begin_ro_txn()
                .map_err(|err| format!("Error beginning transaction to garbage collect: {err}"))?;
            let mut cursor = txn
                .open_ro_cursor(*database)
                .map_err(|err| format!("Failed to open lmdb read cursor: {err}"))?;
            for key_res in cursor.iter() {
                let (key, bytes) =
                    key_res.map_err(|err| format!("Failed to advance lmdb read cursor: {err}"))?;
                *used_bytes += bytes.len();

                // Random access into the lease_database is slower than iterating, but hopefully garbage
                // collection is rare enough that we can get away with this, rather than do two passes
                // here (either to populate leases into pre-populated AgedFingerprints, or to read sizes
                // when we delete from lmdb to track how much we've freed).
                let lease_until_unix_timestamp = txn
                    .get(*lease_database, &key)
                    .map(|b| {
                        let mut array = [0_u8; 8];
                        array.copy_from_slice(b);
                        u64::from_le_bytes(array)
                    })
                    .unwrap_or_else(|e| match e {
                        NotFound => 0,
                        e => panic!("Error reading lease, probable lmdb corruption: {e:?}"),
                    });

                let leased_until =
                    time::UNIX_EPOCH + Duration::from_secs(lease_until_unix_timestamp);

                let expired_seconds_ago = time::SystemTime::now()
                    .duration_since(leased_until)
                    .map(|t| t.as_secs())
                    // 0 indicates unleased.
                    .unwrap_or(0);

                let v = VersionedFingerprint::from_bytes_unsafe(key);
                let fingerprint = v.get_fingerprint();
                fingerprints_by_expired_ago.push(AgedFingerprint {
                    expired_seconds_ago,
                    fingerprint,
                    size_bytes: bytes.len(),
                    entry_type,
                });
            }
        }
        Ok(())
    }

    pub async fn remove(&self, entry_type: EntryType, digest: Digest) -> Result<bool, String> {
        let dbs = match entry_type {
            EntryType::Directory => self.inner.directory_dbs.clone(),
            EntryType::File => self.inner.file_dbs.clone(),
        };
        dbs?.remove(digest.hash).await
    }

    ///
    /// Store the given data in a single pass, using the given Fingerprint. Prefer `Self::store`
    /// for values which should not be pulled into memory, and `Self::store_bytes_batch` when storing
    /// multiple values at a time.
    ///
    pub async fn store_bytes(
        &self,
        entry_type: EntryType,
        fingerprint: Fingerprint,
        bytes: Bytes,
        initial_lease: bool,
    ) -> Result<(), String> {
        let dbs = match entry_type {
            EntryType::Directory => self.inner.directory_dbs.clone(),
            EntryType::File => self.inner.file_dbs.clone(),
        };
        dbs?.store_bytes(fingerprint, bytes, initial_lease).await?;
        Ok(())
    }

    ///
    /// Store the given items in a single pass, optionally using the given Digests. Prefer `Self::store`
    /// for values which should not be pulled into memory.
    ///
    /// See also: `Self::store_bytes`.
    ///
    pub async fn store_bytes_batch(
        &self,
        entry_type: EntryType,
        items: Vec<(Fingerprint, Bytes)>,
        initial_lease: bool,
    ) -> Result<(), String> {
        let dbs = match entry_type {
            EntryType::Directory => self.inner.directory_dbs.clone(),
            EntryType::File => self.inner.file_dbs.clone(),
        };

        dbs?.store_bytes_batch(items, initial_lease).await?;

        Ok(())
    }

    ///
    /// Store data in two passes, without buffering it entirely into memory. Prefer
    /// `Self::store_bytes` for small values which fit comfortably in memory.
    ///
    pub async fn store<F, R>(
        &self,
        entry_type: EntryType,
        initial_lease: bool,
        data_is_immutable: bool,
        data_provider: F,
    ) -> Result<Digest, String>
    where
        R: Read + Debug,
        F: Fn() -> Result<R, io::Error> + Send + 'static,
    {
        let dbs = match entry_type {
            EntryType::Directory => self.inner.directory_dbs.clone(),
            EntryType::File => self.inner.file_dbs.clone(),
        };
        dbs?.store(initial_lease, data_is_immutable, data_provider)
            .await
    }

    ///
    /// Given a collection of Digests (digests),
    /// returns the set of digests from that collection not present in the
    /// underlying LMDB store.
    ///
    pub async fn get_missing_digests(
        &self,
        entry_type: EntryType,
        digests: HashSet<Digest>,
    ) -> Result<HashSet<Digest>, String> {
        let fingerprints_to_check = digests
            .iter()
            .filter_map(|digest| {
                // Avoid I/O for this case. This allows some client-provided operations (like
                // merging snapshots) to work without needing to first store the empty snapshot.
                if *digest == EMPTY_DIGEST {
                    None
                } else {
                    Some(digest.hash)
                }
            })
            .collect::<Vec<_>>();

        let dbs = match entry_type {
            EntryType::Directory => self.inner.directory_dbs.clone(),
            EntryType::File => self.inner.file_dbs.clone(),
        }?;

        let existing = dbs.exists_batch(fingerprints_to_check).await?;

        let missing = digests
            .into_iter()
            .filter(|digest| *digest != EMPTY_DIGEST && !existing.contains(&digest.hash))
            .collect::<HashSet<_>>();
        Ok(missing)
    }

    ///
    /// Loads bytes from the underlying LMDB store using the given function. Because the database is
    /// blocking, this accepts a function that views a slice rather than returning a clone of the
    /// data. The upshot is that the database is able to provide slices directly into shared memory.
    ///
    pub async fn load_bytes_with<
        T: Send + 'static,
        F: FnMut(&[u8]) -> T + Send + Sync + 'static,
    >(
        &self,
        entry_type: EntryType,
        digest: Digest,
        mut f: F,
    ) -> Result<Option<T>, String> {
        let start = Instant::now();
        if digest == EMPTY_DIGEST {
            // Avoid I/O for this case. This allows some client-provided operations (like merging
            // snapshots) to work without needing to first store the empty snapshot.
            return Ok(Some(f(&[])));
        }

        let dbs = match entry_type {
            EntryType::Directory => self.inner.directory_dbs.clone(),
            EntryType::File => self.inner.file_dbs.clone(),
        }?;
        let res = dbs
            .load_bytes_with(digest.hash, move |bytes| {
                if bytes.len() == digest.size_bytes {
                    Ok(f(bytes))
                } else {
                    Err(format!(
            "Got hash collision reading from store - digest {:?} was requested, but retrieved \
                bytes with that fingerprint had length {}. Congratulations, you may have broken \
                sha256! Underlying bytes: {:?}",
            digest,
            bytes.len(),
            bytes
          ))
                }
            })
            .await;

        if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
            workunit_store_handle.store.record_observation(
                ObservationMetric::LocalStoreReadBlobSize,
                digest.size_bytes as u64,
            );
            workunit_store_handle.store.record_observation(
                ObservationMetric::LocalStoreReadBlobTimeMicros,
                start.elapsed().as_micros() as u64,
            );
        }

        res
    }

    pub fn all_digests(&self, entry_type: EntryType) -> Result<Vec<Digest>, String> {
        let database = match entry_type {
            EntryType::File => self.inner.file_dbs.clone(),
            EntryType::Directory => self.inner.directory_dbs.clone(),
        };
        let mut digests = vec![];
        for (env, database, _lease_database) in &database?.all_lmdbs() {
            let txn = env
                .begin_ro_txn()
                .map_err(|err| format!("Error beginning transaction to garbage collect: {err}"))?;
            let mut cursor = txn
                .open_ro_cursor(*database)
                .map_err(|err| format!("Failed to open lmdb read cursor: {err}"))?;
            for key_res in cursor.iter() {
                let (key, bytes) =
                    key_res.map_err(|err| format!("Failed to advance lmdb read cursor: {err}"))?;
                let v = VersionedFingerprint::from_bytes_unsafe(key);
                let fingerprint = v.get_fingerprint();
                digests.push(Digest::new(fingerprint, bytes.len()));
            }
        }
        Ok(digests)
    }
}

#[derive(Eq, PartialEq, Ord, PartialOrd)]
struct AgedFingerprint {
    // expired_seconds_ago must be the first field for the Ord implementation.
    expired_seconds_ago: u64,
    fingerprint: Fingerprint,
    size_bytes: usize,
    entry_type: EntryType,
}
