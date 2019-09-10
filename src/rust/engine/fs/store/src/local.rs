use super::{EntryType, ShrinkBehavior, GIGABYTES};

use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use digest::{Digest as DigestTrait, FixedOutput};
use futures::future::{self, Future};
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use lmdb::Error::NotFound;
use lmdb::{self, Cursor, Database, RwTransaction, Transaction, WriteFlags};
use sha2::Sha256;
use sharded_lmdb::ShardedLmdb;
use std;
use std::collections::BinaryHeap;
use std::path::Path;
use std::sync::Arc;
use std::time;

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
        file_dbs: ShardedLmdb::new(files_root.clone(), 100 * GIGABYTES, executor.clone())
          .map(Arc::new),
        directory_dbs: ShardedLmdb::new(directories_root.clone(), 5 * GIGABYTES, executor.clone())
          .map(Arc::new),
        executor: executor,
      }),
    })
  }

  // Note: This performs IO on the calling thread. Hopefully the IO is small enough not to matter.
  pub fn entry_type(&self, fingerprint: &Fingerprint) -> Result<Option<EntryType>, String> {
    if *fingerprint == EMPTY_DIGEST.0 {
      // Technically this is valid as both; choose Directory in case a caller is checking whether
      // it _can_ be a Directory.
      return Ok(Some(EntryType::Directory));
    }
    {
      let (env, directory_database, _) = self.inner.directory_dbs.clone()?.get(fingerprint);
      let txn = env
        .begin_ro_txn()
        .map_err(|err| format!("Failed to begin read transaction: {:?}", err))?;
      match txn.get(directory_database, &fingerprint.as_ref()) {
        Ok(_) => return Ok(Some(EntryType::Directory)),
        Err(NotFound) => {}
        Err(err) => {
          return Err(format!(
            "Error reading from store when determining type of fingerprint {}: {}",
            fingerprint, err
          ));
        }
      };
    }
    let (env, file_database, _) = self.inner.file_dbs.clone()?.get(fingerprint);
    let txn = env
      .begin_ro_txn()
      .map_err(|err| format!("Failed to begin read transaction: {}", err))?;
    match txn.get(file_database, &fingerprint.as_ref()) {
      Ok(_) => return Ok(Some(EntryType::File)),
      Err(NotFound) => {}
      Err(err) => {
        return Err(format!(
          "Error reading from store when determining type of fingerprint {}: {}",
          fingerprint, err
        ));
      }
    };
    Ok(None)
  }

  pub fn lease_all<'a, Ds: Iterator<Item = &'a Digest>>(&self, digests: Ds) -> Result<(), String> {
    let until = Self::default_lease_until_secs_since_epoch();
    for digest in digests {
      let (env, _, lease_database) = self.inner.file_dbs.clone()?.get(&digest.0);
      env
        .begin_rw_txn()
        .and_then(|mut txn| self.lease(lease_database, &digest.0, until, &mut txn))
        .map_err(|err| format!("Error leasing digest {:?}: {}", digest, err))?;
    }
    Ok(())
  }

  fn default_lease_until_secs_since_epoch() -> u64 {
    let now_since_epoch = time::SystemTime::now()
      .duration_since(time::UNIX_EPOCH)
      .expect("Surely you're not before the unix epoch?");
    (now_since_epoch + time::Duration::from_secs(2 * 60 * 60)).as_secs()
  }

  fn lease(
    &self,
    database: Database,
    fingerprint: &Fingerprint,
    until_secs_since_epoch: u64,
    txn: &mut RwTransaction<'_>,
  ) -> Result<(), lmdb::Error> {
    txn.put(
      database,
      &fingerprint.as_ref(),
      &until_secs_since_epoch.to_le_bytes(),
      WriteFlags::empty(),
    )
  }

  ///
  /// Attempts to shrink the stored files to be no bigger than target_bytes
  /// (excluding lmdb overhead).
  ///
  /// Returns the size it was shrunk to, which may be larger than target_bytes.
  ///
  /// Ignores directories. TODO: Shrink directories.
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
            txn.del(database, &aged_fingerprint.fingerprint.as_ref(), None)?;

            txn
              .del(lease_database, &aged_fingerprint.fingerprint.as_ref(), None)
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

        let leased_until = time::UNIX_EPOCH + time::Duration::from_secs(lease_until_unix_timestamp);

        let expired_seconds_ago = time::SystemTime::now()
          .duration_since(leased_until)
          .map(|t| t.as_secs())
          // 0 indicates unleased.
          .unwrap_or(0);

        fingerprints_by_expired_ago.push(AgedFingerprint {
          expired_seconds_ago: expired_seconds_ago,
          fingerprint: Fingerprint::from_bytes_unsafe(key),
          size_bytes: bytes.len(),
          entry_type: entry_type,
        });
      }
    }
    Ok(())
  }

  pub fn store_bytes(
    &self,
    entry_type: EntryType,
    bytes: Bytes,
    initial_lease: bool,
  ) -> impl Future<Item = Digest, Error = String> {
    let dbs = match entry_type {
      EntryType::Directory => self.inner.directory_dbs.clone(),
      EntryType::File => self.inner.file_dbs.clone(),
    };
    let bytes2 = bytes.clone();
    self
      .inner
      .executor
      .spawn_on_io_pool(futures::future::lazy(move || {
        let fingerprint = {
          let mut hasher = Sha256::default();
          hasher.input(&bytes);
          Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
        };
        Ok(Digest(fingerprint, bytes.len()))
      }))
      .and_then(move |digest| {
        future::done(dbs)
          .and_then(move |db| db.store_bytes(digest.0, bytes2, initial_lease))
          .map(move |()| digest)
      })
  }

  pub fn load_bytes_with<T: Send + 'static, F: Fn(Bytes) -> T + Send + Sync + 'static>(
    &self,
    entry_type: EntryType,
    digest: Digest,
    f: F,
  ) -> BoxFuture<Option<T>, String> {
    if digest == EMPTY_DIGEST {
      // Avoid expensive I/O for this super common case.
      // Also, this allows some client-provided operations (like merging snapshots) to work
      // without needing to first store the empty snapshot.
      return future::ok(Some(f(Bytes::new()))).to_boxed();
    }

    let dbs = match entry_type {
      EntryType::Directory => self.inner.directory_dbs.clone(),
      EntryType::File => self.inner.file_dbs.clone(),
    };

    try_future!(dbs).load_bytes_with(digest.0, move |bytes| {
                if bytes.len() == digest.1 {
                    Ok(f(bytes))
                } else {
                    Err(format!("Got hash collision reading from store - digest {:?} was requested, but retrieved bytes with that fingerprint had length {}. Congratulations, you may have broken sha256! Underlying bytes: {:?}", digest, bytes.len(), bytes))
                }
            }).to_boxed()
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
        digests.push(Digest(Fingerprint::from_bytes_unsafe(key), bytes.len()));
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

#[cfg(test)]
pub mod tests {
  use super::super::tests::block_on;
  use super::{ByteStore, EntryType, ShrinkBehavior};
  use bytes::{BufMut, Bytes, BytesMut};
  use hashing::{Digest, Fingerprint};
  use std::path::Path;
  use tempfile::TempDir;
  use testutil::data::{TestData, TestDirectory};
  use walkdir::WalkDir;

  #[test]
  fn save_file() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();
    assert_eq!(
      block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false,)),
      Ok(testdata.digest())
    );
  }

  #[test]
  fn save_file_is_idempotent() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();
    block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false)).unwrap();
    assert_eq!(
      block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false,)),
      Ok(testdata.digest())
    );
  }

  #[test]
  fn roundtrip_file() {
    let testdata = TestData::roland();
    let dir = TempDir::new().unwrap();

    let store = new_store(dir.path());
    let hash = prime_store_with_file_bytes(&store, testdata.bytes());
    assert_eq!(load_file_bytes(&store, hash), Ok(Some(testdata.bytes())));
  }

  #[test]
  fn missing_file() {
    let dir = TempDir::new().unwrap();
    assert_eq!(
      load_file_bytes(&new_store(dir.path()), TestData::roland().digest()),
      Ok(None)
    );
  }

  #[test]
  fn record_and_load_directory_proto() {
    let dir = TempDir::new().unwrap();
    let testdir = TestDirectory::containing_roland();

    assert_eq!(
      block_on(new_store(dir.path()).store_bytes(EntryType::Directory, testdir.bytes(), false,)),
      Ok(testdir.digest())
    );

    assert_eq!(
      load_directory_proto_bytes(&new_store(dir.path()), testdir.digest()),
      Ok(Some(testdir.bytes()))
    );
  }

  #[test]
  fn missing_directory() {
    let dir = TempDir::new().unwrap();
    let testdir = TestDirectory::containing_roland();

    assert_eq!(
      load_directory_proto_bytes(&new_store(dir.path()), testdir.digest()),
      Ok(None)
    );
  }

  #[test]
  fn file_is_not_directory_proto() {
    let dir = TempDir::new().unwrap();
    let testdata = TestData::roland();

    block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false)).unwrap();

    assert_eq!(
      load_directory_proto_bytes(&new_store(dir.path()), testdata.digest()),
      Ok(None)
    );
  }

  #[test]
  fn garbage_collect_nothing_to_do() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let bytes = Bytes::from("0123456789");
    block_on(store.store_bytes(EntryType::File, bytes.clone(), false)).expect("Error storing");
    store
      .shrink(10, ShrinkBehavior::Fast)
      .expect("Error shrinking");
    assert_eq!(
      load_bytes(
        &store,
        EntryType::File,
        Digest(
          Fingerprint::from_hex_string(
            "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
          )
          .unwrap(),
          10
        )
      ),
      Ok(Some(bytes))
    );
  }

  #[test]
  fn garbage_collect_nothing_to_do_with_lease() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let bytes = Bytes::from("0123456789");
    block_on(store.store_bytes(EntryType::File, bytes.clone(), false)).expect("Error storing");
    let file_fingerprint = Fingerprint::from_hex_string(
      "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
    )
    .unwrap();
    let file_digest = Digest(file_fingerprint, 10);
    store
      .lease_all(vec![file_digest].iter())
      .expect("Error leasing");
    store
      .shrink(10, ShrinkBehavior::Fast)
      .expect("Error shrinking");
    assert_eq!(
      load_bytes(&store, EntryType::File, file_digest),
      Ok(Some(bytes))
    );
  }

  #[test]
  fn garbage_collect_remove_one_of_two_files_no_leases() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let bytes_1 = Bytes::from("0123456789");
    let fingerprint_1 = Fingerprint::from_hex_string(
      "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
    )
    .unwrap();
    let digest_1 = Digest(fingerprint_1, 10);
    let bytes_2 = Bytes::from("9876543210");
    let fingerprint_2 = Fingerprint::from_hex_string(
      "7619ee8cea49187f309616e30ecf54be072259b43760f1f550a644945d5572f2",
    )
    .unwrap();
    let digest_2 = Digest(fingerprint_2, 10);
    block_on(store.store_bytes(EntryType::File, bytes_1.clone(), false)).expect("Error storing");
    block_on(store.store_bytes(EntryType::File, bytes_2.clone(), false)).expect("Error storing");
    store
      .shrink(10, ShrinkBehavior::Fast)
      .expect("Error shrinking");
    let mut entries = Vec::new();
    entries.push(load_bytes(&store, EntryType::File, digest_1).expect("Error loading bytes"));
    entries.push(load_bytes(&store, EntryType::File, digest_2).expect("Error loading bytes"));
    assert_eq!(
      1,
      entries.iter().filter(|maybe| maybe.is_some()).count(),
      "Want one Some but got: {:?}",
      entries
    );
  }

  #[test]
  fn garbage_collect_remove_both_files_no_leases() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let bytes_1 = Bytes::from("0123456789");
    let fingerprint_1 = Fingerprint::from_hex_string(
      "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
    )
    .unwrap();
    let digest_1 = Digest(fingerprint_1, 10);
    let bytes_2 = Bytes::from("9876543210");
    let fingerprint_2 = Fingerprint::from_hex_string(
      "7619ee8cea49187f309616e30ecf54be072259b43760f1f550a644945d5572f2",
    )
    .unwrap();
    let digest_2 = Digest(fingerprint_2, 10);
    block_on(store.store_bytes(EntryType::File, bytes_1.clone(), false)).expect("Error storing");
    block_on(store.store_bytes(EntryType::File, bytes_2.clone(), false)).expect("Error storing");
    store
      .shrink(1, ShrinkBehavior::Fast)
      .expect("Error shrinking");
    assert_eq!(
      load_bytes(&store, EntryType::File, digest_1),
      Ok(None),
      "Should have garbage collected {:?}",
      fingerprint_1
    );
    assert_eq!(
      load_bytes(&store, EntryType::File, digest_2),
      Ok(None),
      "Should have garbage collected {:?}",
      fingerprint_2
    );
  }

  #[test]
  fn garbage_collect_remove_one_of_two_directories_no_leases() {
    let dir = TempDir::new().unwrap();

    let testdir = TestDirectory::containing_roland();
    let other_testdir = TestDirectory::containing_dnalor();

    let store = new_store(dir.path());
    block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false))
      .expect("Error storing");
    block_on(store.store_bytes(EntryType::Directory, other_testdir.bytes(), false))
      .expect("Error storing");
    store
      .shrink(80, ShrinkBehavior::Fast)
      .expect("Error shrinking");
    let mut entries = Vec::new();
    entries.push(
      load_bytes(&store, EntryType::Directory, testdir.digest()).expect("Error loading bytes"),
    );
    entries.push(
      load_bytes(&store, EntryType::Directory, other_testdir.digest())
        .expect("Error loading bytes"),
    );
    assert_eq!(
      1,
      entries.iter().filter(|maybe| maybe.is_some()).count(),
      "Want one Some but got: {:?}",
      entries
    );
  }

  #[test]
  fn garbage_collect_remove_file_with_leased_directory() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());

    let testdir = TestDirectory::containing_roland();
    let testdata = TestData::fourty_chars();

    block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), true))
      .expect("Error storing");

    block_on(store.store_bytes(EntryType::File, testdata.bytes(), false)).expect("Error storing");

    store
      .shrink(80, ShrinkBehavior::Fast)
      .expect("Error shrinking");

    assert_eq!(
      load_bytes(&store, EntryType::File, testdata.digest()),
      Ok(None),
      "File was present when it should've been garbage collected"
    );
    assert_eq!(
      load_bytes(&store, EntryType::Directory, testdir.digest()),
      Ok(Some(testdir.bytes())),
      "Directory was missing despite lease"
    );
  }

  #[test]
  fn garbage_collect_remove_file_while_leased_file() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());

    let testdir = TestDirectory::containing_roland();

    block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false))
      .expect("Error storing");
    let fourty_chars = TestData::fourty_chars();
    block_on(store.store_bytes(EntryType::File, fourty_chars.bytes(), true))
      .expect("Error storing");

    store
      .shrink(80, ShrinkBehavior::Fast)
      .expect("Error shrinking");

    assert_eq!(
      load_bytes(&store, EntryType::File, fourty_chars.digest()),
      Ok(Some(fourty_chars.bytes())),
      "File was missing despite lease"
    );
    assert_eq!(
      load_bytes(&store, EntryType::Directory, testdir.digest()),
      Ok(None),
      "Directory was present when it should've been garbage collected"
    );
  }

  #[test]
  fn garbage_collect_fail_because_too_many_leases() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());

    let testdir = TestDirectory::containing_roland();
    let fourty_chars = TestData::fourty_chars();

    block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), true))
      .expect("Error storing");
    block_on(store.store_bytes(EntryType::File, fourty_chars.bytes(), true))
      .expect("Error storing");

    block_on(store.store_bytes(EntryType::File, TestData::roland().bytes(), false))
      .expect("Error storing");

    assert_eq!(store.shrink(80, ShrinkBehavior::Fast), Ok(160));

    assert_eq!(
      load_bytes(&store, EntryType::File, fourty_chars.digest()),
      Ok(Some(fourty_chars.bytes())),
      "Leased file should still be present"
    );
    assert_eq!(
      load_bytes(&store, EntryType::Directory, testdir.digest()),
      Ok(Some(testdir.bytes())),
      "Leased directory should still be present"
    );
    // Whether the unleased file is present is undefined.
  }

  #[test]
  fn garbage_collect_and_compact() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());

    let write_one_meg = |byte: u8| {
      let mut bytes = BytesMut::with_capacity(1024 * 1024);
      for _ in 0..1024 * 1024 {
        bytes.put(byte);
      }
      block_on(store.store_bytes(EntryType::File, bytes.freeze(), false)).expect("Error storing");
    };

    write_one_meg(b'0');

    write_one_meg(b'1');

    let size = get_directory_size(dir.path());
    assert!(
      size >= 2 * 1024 * 1024,
      "Expect size to be at least 2MB but was {}",
      size
    );

    store
      .shrink(1024 * 1024, ShrinkBehavior::Compact)
      .expect("Error shrinking");

    let size = get_directory_size(dir.path());
    assert!(
      size < 2 * 1024 * 1024,
      "Expect size to be less than 2MB but was {}",
      size
    );
  }

  #[test]
  fn entry_type_for_file() {
    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false))
      .expect("Error storing");
    prime_store_with_file_bytes(&store, testdata.bytes());
    assert_eq!(
      store.entry_type(&testdata.fingerprint()),
      Ok(Some(EntryType::File))
    )
  }

  #[test]
  fn entry_type_for_directory() {
    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false))
      .expect("Error storing");
    prime_store_with_file_bytes(&store, testdata.bytes());
    assert_eq!(
      store.entry_type(&testdir.fingerprint()),
      Ok(Some(EntryType::Directory))
    )
  }

  #[test]
  fn entry_type_for_missing() {
    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false))
      .expect("Error storing");
    prime_store_with_file_bytes(&store, testdata.bytes());
    assert_eq!(
      store.entry_type(&TestDirectory::recursive().fingerprint()),
      Ok(None)
    )
  }

  #[test]
  pub fn empty_file_is_known() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let empty_file = TestData::empty();
    assert_eq!(
      block_on(store.load_bytes_with(EntryType::File, empty_file.digest(), |b| b)),
      Ok(Some(empty_file.bytes())),
    )
  }

  #[test]
  pub fn empty_directory_is_known() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let empty_dir = TestDirectory::empty();
    assert_eq!(
      block_on(store.load_bytes_with(EntryType::Directory, empty_dir.digest(), |b| b)),
      Ok(Some(empty_dir.bytes())),
    )
  }

  #[test]
  pub fn all_digests() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let digest = prime_store_with_file_bytes(&store, TestData::roland().bytes());
    assert_eq!(Ok(vec![digest]), store.all_digests(EntryType::File));
  }

  pub fn new_store<P: AsRef<Path>>(dir: P) -> ByteStore {
    ByteStore::new(task_executor::Executor::new(), dir).unwrap()
  }

  pub fn load_file_bytes(store: &ByteStore, digest: Digest) -> Result<Option<Bytes>, String> {
    load_bytes(&store, EntryType::File, digest)
  }

  pub fn load_directory_proto_bytes(
    store: &ByteStore,
    digest: Digest,
  ) -> Result<Option<Bytes>, String> {
    load_bytes(&store, EntryType::Directory, digest)
  }

  fn load_bytes(
    store: &ByteStore,
    entry_type: EntryType,
    digest: Digest,
  ) -> Result<Option<Bytes>, String> {
    block_on(store.load_bytes_with(entry_type, digest, |b| b))
  }

  fn prime_store_with_file_bytes(store: &ByteStore, bytes: Bytes) -> Digest {
    block_on(store.store_bytes(EntryType::File, bytes, false)).expect("Error storing file bytes")
  }

  fn get_directory_size(path: &Path) -> usize {
    let mut len: usize = 0;
    for entry in WalkDir::new(path) {
      len += entry
        .expect("Error walking directory")
        .metadata()
        .expect("Error reading metadata")
        .len() as usize;
    }
    len
  }
}
