use super::{EntryType, ShrinkBehavior, GIGABYTES};

use std::collections::BinaryHeap;
use std::path::Path;
use std::sync::Arc;
use std::time::{self, Duration};

use bytes::Bytes;
use digest::{Digest as DigestTrait, FixedOutput};
use futures::future;
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use lmdb::Error::NotFound;
use lmdb::{self, Cursor, Transaction};
use sha2::Sha256;
use sharded_lmdb::{ShardedLmdb, VersionedFingerprint, DEFAULT_LEASE_TIME};

#[derive(Clone)]
pub struct ByteStore {
  inner: Arc<InnerStore>,
}

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
    Self::new_with_lease_time(executor, path, DEFAULT_LEASE_TIME)
  }

  pub fn new_with_lease_time<P: AsRef<Path>>(
    executor: task_executor::Executor,
    path: P,
    lease_time: Duration,
  ) -> Result<ByteStore, String> {
    let root = path.as_ref();
    let files_root = root.join("files");
    let directories_root = root.join("directories");
    Ok(ByteStore {
      inner: Arc::new(InnerStore {
        // We want these stores to be allowed to grow very large, in case we are on a system with
        // large disks which doesn't want to GC a lot.
        // It doesn't reflect space allocated on disk, or RAM allocated (it may be reflected in
        // VIRT but not RSS). There is no practical upper bound on this number, so we set them
        // ridiculously high.
        // However! We set them lower than we'd otherwise choose because sometimes we see tests on
        // travis fail because they can't allocate virtual memory, if there are multiple Stores
        // in memory at the same time. We don't know why they're not efficiently garbage collected
        // by python, but they're not, so...
        file_dbs: ShardedLmdb::new(files_root, 100 * GIGABYTES, executor.clone(), lease_time)
          .map(Arc::new),
        directory_dbs: ShardedLmdb::new(
          directories_root,
          5 * GIGABYTES,
          executor.clone(),
          lease_time,
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
    if fingerprint == EMPTY_DIGEST.0 {
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
      dbs?
        .lease(digest.0)
        .await
        .map_err(|err| format!("Error leasing digest {:?}: {}", digest, err))?;
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
            let key = VersionedFingerprint::new(
              aged_fingerprint.fingerprint,
              ShardedLmdb::schema_version(),
            );
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
          .map_err(|err| format!("Error garbage collecting: {}", err))?;
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

    for &(ref env, ref database, ref lease_database) in &database?.all_lmdbs() {
      let txn = env
        .begin_ro_txn()
        .map_err(|err| format!("Error beginning transaction to garbage collect: {}", err))?;
      let mut cursor = txn
        .open_ro_cursor(*database)
        .map_err(|err| format!("Failed to open lmdb read cursor: {}", err))?;
      for (key, bytes) in cursor.iter() {
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
            e => panic!("Error reading lease, probable lmdb corruption: {:?}", e),
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
    let dbs = match entry_type {
      EntryType::Directory => self.inner.directory_dbs.clone(),
      EntryType::File => self.inner.file_dbs.clone(),
    };
    dbs?.remove(digest.0).await
  }

  pub async fn store_bytes(
    &self,
    entry_type: EntryType,
    bytes: Bytes,
    initial_lease: bool,
  ) -> Result<Digest, String> {
    let dbs = match entry_type {
      EntryType::Directory => self.inner.directory_dbs.clone(),
      EntryType::File => self.inner.file_dbs.clone(),
    };
    let bytes2 = bytes.clone();
    let digest = self
      .inner
      .executor
      .spawn_blocking(move || {
        let fingerprint = {
          let mut hasher = Sha256::default();
          hasher.input(&bytes);
          Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
        };
        Digest(fingerprint, bytes.len())
      })
      .await;
    dbs?.store_bytes(digest.0, bytes2, initial_lease).await?;
    Ok(digest)
  }

  ///
  /// Loads bytes from the underlying LMDB store using the given function. Because the database is
  /// blocking, this accepts a function that views a slice rather than returning a clone of the
  /// data. The upshot is that the database is able to provide slices directly into shared memory.
  ///
  /// The provided function is guaranteed to be called in a context where it is safe to block.
  ///
  pub async fn load_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
    &self,
    entry_type: EntryType,
    digest: Digest,
    f: F,
  ) -> Result<Option<T>, String> {
    if digest == EMPTY_DIGEST {
      // Avoid I/O for this case. This allows some client-provided operations (like merging
      // snapshots) to work without needing to first store the empty snapshot.
      //
      // To maintain the guarantee that the given function is called in a blocking context, we
      // spawn it as a task.
      return Ok(Some(self.executor().spawn_blocking(move || f(&[])).await));
    }

    let dbs = match entry_type {
      EntryType::Directory => self.inner.directory_dbs.clone(),
      EntryType::File => self.inner.file_dbs.clone(),
    };

    dbs?.load_bytes_with(digest.0, move |bytes| {
        if bytes.len() == digest.1 {
            Ok(f(bytes))
        } else {
            Err(format!("Got hash collision reading from store - digest {:?} was requested, but retrieved bytes with that fingerprint had length {}. Congratulations, you may have broken sha256! Underlying bytes: {:?}", digest, bytes.len(), bytes))
        }
    }).await
  }

  pub fn all_digests(&self, entry_type: EntryType) -> Result<Vec<Digest>, String> {
    let database = match entry_type {
      EntryType::File => self.inner.file_dbs.clone(),
      EntryType::Directory => self.inner.directory_dbs.clone(),
    };
    let mut digests = vec![];
    for &(ref env, ref database, ref _lease_database) in &database?.all_lmdbs() {
      let txn = env
        .begin_ro_txn()
        .map_err(|err| format!("Error beginning transaction to garbage collect: {}", err))?;
      let mut cursor = txn
        .open_ro_cursor(*database)
        .map_err(|err| format!("Failed to open lmdb read cursor: {}", err))?;
      for (key, bytes) in cursor.iter() {
        let v = VersionedFingerprint::from_bytes_unsafe(key);
        let fingerprint = v.get_fingerprint();
        digests.push(Digest(fingerprint, bytes.len()));
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
