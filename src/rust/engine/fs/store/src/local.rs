// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use super::{EntryType, ShrinkBehavior};

use std::collections::{BinaryHeap, HashSet};
use std::fmt::Debug;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{self, Duration, Instant};

use bytes::{Buf, Bytes};
use futures::future::{self, join_all, try_join, try_join_all};
use hashing::{async_verified_copy, hash, hash_path, Digest, Fingerprint, EMPTY_DIGEST};
use lmdb::Error::NotFound;
use lmdb::{self, Cursor, Transaction};
use sharded_lmdb::{ShardedLmdb, VersionedFingerprint};
use std::os::unix::fs::PermissionsExt;
use tempfile::NamedTempFile;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use workunit_store::ObservationMetric;

/// How big a file must be to be stored as a file on disk.
// NB: These numbers were chosen after micro-benchmarking the code on one machine at the time of
// writing. They were chosen using a rough equation from the microbenchmarks that are optimized
// for somewhere between 2 and 3 uses of the corresponding entry to "break even".
const LARGE_FILE_SIZE_LIMIT: usize = 512 * 1024;

#[derive(Debug, Clone)]
pub struct TempImmutableLargeFile {
  tmp_path: PathBuf,
  final_path: PathBuf,
}

impl TempImmutableLargeFile {
  pub async fn open(&self) -> tokio::io::Result<tokio::fs::File> {
    tokio::fs::File::create(self.tmp_path.clone()).await
  }

  pub async fn persist(&self) -> Result<(), String> {
    tokio::fs::rename(self.tmp_path.clone(), self.final_path.clone())
      .await
      .map_err(|e| format!("Error while renaming: {e}."))?;
    tokio::fs::set_permissions(&self.final_path, std::fs::Permissions::from_mode(0o555))
      .await
      .map_err(|e| e.to_string())?;
    Ok(())
  }
}

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
  large_files_root: PathBuf,
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
    let large_files_root = root.join("immutable");

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
        large_files_root,
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

    async fn exists(path: PathBuf) -> Result<bool, String> {
      Ok(tokio::fs::File::open(path).await.is_ok())
    }

    // In parallel, check for the given fingerprint in both databases.
    let d_dbs = self.inner.directory_dbs.clone()?;
    let is_dir = d_dbs.exists(fingerprint);
    let f_dbs = self.inner.file_dbs.clone()?;
    let is_dbs_file = f_dbs.exists(fingerprint);
    let is_immut_file = exists(self.large_file_path(fingerprint));

    // TODO: Could technically use select to return slightly more quickly with the first
    // affirmative answer, but this is simpler.
    match future::try_join3(is_dir, is_dbs_file, is_immut_file).await? {
      (true, _, _) => Ok(Some(EntryType::Directory)),
      (_, true, _) => Ok(Some(EntryType::File)),
      (_, _, true) => Ok(Some(EntryType::File)),
      (false, false, false) => Ok(None),
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
      dbs?
        .lease(digest.hash)
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
        env
          .begin_rw_txn()
          .and_then(|mut txn| {
            let key =
              VersionedFingerprint::new(aged_fingerprint.fingerprint, ShardedLmdb::SCHEMA_VERSION);
            txn.del(database, &key, None)?;

            txn
              .del(lease_database, &key, None)
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

        let leased_until = time::UNIX_EPOCH + Duration::from_secs(lease_until_unix_timestamp);

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
    if entry_type == EntryType::File && ByteStore::uses_large_file_store(digest.size_bytes) {
      let path = self.large_file_path(digest.hash);
      return Ok(tokio::fs::remove_file(path).await.is_ok());
    }

    let dbs = match entry_type {
      EntryType::Directory => self.inner.directory_dbs.clone(),
      EntryType::File => self.inner.file_dbs.clone(),
    };
    dbs?.remove(digest.hash).await
  }

  ///
  /// Store the given data in a single pass, optionally using the given Digest. Prefer `Self::store`
  /// for values which should not be pulled into memory, and `Self::store_bytes_batch` when storing
  /// multiple values at a time.
  ///
  pub async fn store_bytes(
    &self,
    entry_type: EntryType,
    digest: Option<Digest>,
    bytes: Bytes,
    initial_lease: bool,
  ) -> Result<Digest, String> {
    let len = bytes.len();
    if entry_type == EntryType::File && ByteStore::uses_large_file_store(len) {
      Ok(self.store_large_bytes(bytes, digest).await?)
    } else {
      let dbs = match entry_type {
        EntryType::Directory => self.inner.directory_dbs.clone(),
        EntryType::File => self.inner.file_dbs.clone(),
      };
      let fingerprint = dbs?
        .store_bytes(digest.map(|d| d.hash), bytes, initial_lease)
        .await?;

      Ok(Digest::new(fingerprint, len))
    }
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
    items: Vec<(Option<Digest>, Bytes)>,
    initial_lease: bool,
  ) -> Result<Vec<Digest>, String> {
    let mut small_items = vec![];
    let mut big_items = vec![];
    for (digest, bytes) in items {
      if entry_type == EntryType::File && ByteStore::uses_large_file_store(bytes.len()) {
        big_items.push((digest, bytes));
      } else {
        small_items.push((digest, bytes));
      }
    }
    let mut result = try_join_all(
      big_items
        .iter()
        .map(|(digest, bytes)| self.store_large_bytes(bytes.clone(), *digest)),
    )
    .await?;

    let dbs = match entry_type {
      EntryType::Directory => self.inner.directory_dbs.clone(),
      EntryType::File => self.inner.file_dbs.clone(),
    };
    // NB: False positive: we do actually need to create the Vec here, since `items` will move
    // before we use `lens`.
    #[allow(clippy::needless_collect)]
    let lens = small_items
      .iter()
      .map(|(_, bytes)| bytes.len())
      .collect::<Vec<_>>();
    let fingerprints = dbs?
      .store_bytes_batch(
        small_items
          .into_iter()
          .map(|(d, bytes)| (d.map(|d| d.hash), bytes))
          .collect(),
        initial_lease,
      )
      .await?;

    result.extend(
      fingerprints
        .into_iter()
        .zip(lens.into_iter())
        .map(|(f, len)| Digest::new(f, len)),
    );

    Ok(result)
  }

  /// Returns whether this file digest should/does use the "large file store" instead of the LMDB.
  pub(crate) fn uses_large_file_store(len: usize) -> bool {
    len > LARGE_FILE_SIZE_LIMIT
  }

  /// Assuming uses_large_file_store(digest) is true, return the path inside the store.
  pub fn large_file_path(&self, fingerprint: Fingerprint) -> PathBuf {
    let hex = fingerprint.to_hex();
    // We use 2-character directories to help shard the files so there isn't a plethora in one single dir.
    self
      .inner
      .large_files_root
      .join(hex.get(0..2).unwrap())
      .join(hex)
  }

  ///
  /// Store data in two passes, without buffering it entirely into memory. Prefer
  /// `Self::store_bytes` for small values which fit comfortably in memory.
  ///
  pub async fn store(
    &self,
    entry_type: EntryType,
    initial_lease: bool,
    data_is_immutable: bool,
    src: PathBuf,
  ) -> Result<Digest, String> {
    let digest = hash_path(src.clone())?;

    if ByteStore::uses_large_file_store(digest.size_bytes) {
      self
        .store_large_file(src, digest, data_is_immutable)
        .await?;
    } else {
      let dbs = match entry_type {
        EntryType::Directory => self.inner.directory_dbs.clone(),
        EntryType::File => self.inner.file_dbs.clone(),
      };
      let _ = dbs?
        .store(initial_lease, data_is_immutable, digest, move || {
          std::fs::File::open(&src)
        })
        .await;
    }

    Ok(digest)
  }

  ///
  /// Determine which of the given Fingerprints are already present in the large file store,
  /// returning them as a set.
  ///
  async fn get_existing_large_fingerprints(
    &self,
    fingerprints: Vec<Fingerprint>,
  ) -> HashSet<Fingerprint> {
    let paths_to_check = fingerprints
      .iter()
      .map(|fingerprint| self.large_file_path(*fingerprint))
      .collect::<Vec<_>>();

    #[allow(clippy::redundant_closure)]
    let results = join_all(
      paths_to_check
        .iter()
        .map(|path| tokio::fs::File::open(path)),
    )
    .await;
    let existing = results
      .iter()
      .zip(fingerprints)
      .filter_map(|(result, fingerprint)| {
        if result.is_ok() {
          Some(fingerprint)
        } else {
          None
        }
      })
      .collect::<Vec<_>>();

    HashSet::from_iter(existing)
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
    let mut large_file_digests = vec![];
    let mut other_digests = vec![];
    for digest in digests.iter() {
      if entry_type == EntryType::File && ByteStore::uses_large_file_store(digest.size_bytes) {
        large_file_digests.push(digest);
      }
      // Avoid I/O for this case. This allows some client-provided operations (like
      // merging snapshots) to work without needing to first store the empty snapshot.
      else if *digest != EMPTY_DIGEST {
        other_digests.push(digest);
      }
    }

    let mut existing = HashSet::new();
    if !large_file_digests.is_empty() {
      existing.extend(
        self
          .get_existing_large_fingerprints(
            large_file_digests
              .iter()
              .map(|digest| digest.hash)
              .collect(),
          )
          .await,
      );
    }

    if !other_digests.is_empty() {
      let dbs = match entry_type {
        EntryType::Directory => self.inner.directory_dbs.clone(),
        EntryType::File => self.inner.file_dbs.clone(),
      }?;
      existing.extend(
        dbs
          .exists_batch(other_digests.iter().map(|digest| digest.hash).collect())
          .await?,
      );
    }

    let missing = digests
      .into_iter()
      .filter(|digest| *digest != EMPTY_DIGEST && !existing.contains(&digest.hash))
      .collect::<HashSet<_>>();
    Ok(missing)
  }

  ///
  /// Loads bytes from the underlying store using the given function.
  /// In the case of the LMDB store, because the database is blocking, this accepts a function that
  /// views a slice rather than returning a clone of the data.
  /// The upshot is that the database is able to provide slices directly into shared memory.
  ///
  pub async fn load_bytes_with<T: Send + 'static, F: FnMut(&[u8]) -> T + Send + Sync + 'static>(
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

    let res = if ByteStore::uses_large_file_store(digest.size_bytes) {
      let src = &self.large_file_path(digest.hash);
      let file_result = tokio::fs::File::open(src).await;
      if let Ok(mut file) = file_result {
        // @TODO: Use mmap instead of copying into user-space
        let mut contents: Vec<u8> = vec![];
        file
          .read_to_end(&mut contents)
          .await
          .map_err(|e| format!("Failed to load large file into memory: {e}"))?;
        if contents.len() != digest.size_bytes {
          return Err(format!(
            "Got hash collision reading from store - digest {:?} was requested, but retrieved \
                bytes with that fingerprint had length {}. Congratulations, you may have broken \
                sha256! Underlying bytes: {:?}",
            digest,
            contents.len(),
            contents
          ));
        }
        Ok(Some(f(&contents[..])))
      } else {
        Ok(None)
      }
    } else {
      let dbs = match entry_type {
        EntryType::Directory => self.inner.directory_dbs.clone(),
        EntryType::File => self.inner.file_dbs.clone(),
      }?;
      dbs
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
        .await
    };

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
    if entry_type == EntryType::File {
      let maybe_shards = std::fs::read_dir(self.inner.large_files_root.clone());
      if let Ok(shards) = maybe_shards {
        for entry in shards {
          let shard = entry.map_err(|e| format!("Error iterating the large file store: {e}."))?;
          let large_files = std::fs::read_dir(shard.path())
            .map_err(|e| format!("Failed to read shard directory: {e}."))?;
          for entry in large_files {
            let large_file = entry.map_err(|e| {
              format!(
                "Error iterating large file store shard {:?}: {e}",
                shard.path().file_name()
              )
            })?;
            let path = large_file.path();
            let hash = path.file_name().unwrap().to_str().unwrap();
            let length = large_file.metadata().map_err(|e| e.to_string())?.len();
            digests.push(Digest::new(
              Fingerprint::from_hex_string(hash).unwrap(),
              length as usize,
            ));
          }
        }
      }
    }
    Ok(digests)
  }

  pub(crate) async fn get_temp_immutable_large_file(
    &self,
    digest: Digest,
  ) -> Result<TempImmutableLargeFile, String> {
    let dest = self.large_file_path(digest.hash);
    if !dest.parent().unwrap().exists() {
      // Throwaway the result as a way of not worrying about race conditions between multiple
      // threads/processes creating the same parent dirs. If there was an error we'll fail later.
      let _ = tokio::fs::create_dir_all(dest.parent().unwrap()).await;
    }
    let dest2 = dest.clone();
    // Make the tempdir in the same dir as the final file so that materializing the final file doesn't
    // have to worry about parent dirs.
    let named_temp_file =
      tokio::task::spawn_blocking(move || NamedTempFile::new_in(dest.parent().unwrap()))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?;
    let (_, path) = named_temp_file.keep().map_err(|e| e.to_string())?;
    Ok(TempImmutableLargeFile {
      tmp_path: path,
      final_path: dest2,
    })
  }

  async fn store_large_bytes(
    &self,
    src: Bytes,
    mut digest: Option<Digest>,
  ) -> Result<Digest, String> {
    if digest.is_none() {
      digest =
        Some(hash(&mut src.clone().reader()).map_err(|e| format!("Failed to hash bytes: {e}"))?);
    }
    let dest = self.get_temp_immutable_large_file(digest.unwrap()).await?;
    let mut dest_file = dest.open().await.map_err(|e| e.to_string())?;
    dest_file
      .write_all(&src.clone())
      .await
      .map_err(|e| e.to_string())?;
    dest_file.flush().await.map_err(|e| e.to_string())?;
    dest.persist().await?;
    Ok(digest.unwrap())
  }

  async fn store_large_file(
    &self,
    src: PathBuf,
    digest: Digest,
    data_is_immutable: bool,
  ) -> Result<(), String> {
    let dest = self.get_temp_immutable_large_file(digest).await?;
    let mut attempts = 0;
    loop {
      let (mut reader, mut writer) =
        try_join(tokio::fs::File::open(src.clone()), dest.clone().open())
          .await
          .map_err(|e| e.to_string())?;
      let should_retry = !async_verified_copy(digest, data_is_immutable, &mut reader, &mut writer)
        .await
        .map_err(|e| e.to_string())?;

      if should_retry {
        attempts += 1;
        let msg = format!("Input {src:?} changed while reading.");
        log::debug!("{}", msg);
        if attempts > 10 {
          return Err(format!("Failed to store {src:?}."));
        }
      } else {
        writer.flush().await.map_err(|e| e.to_string())?;
        dest.persist().await?;
        break;
      }
    }

    Ok(())
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
