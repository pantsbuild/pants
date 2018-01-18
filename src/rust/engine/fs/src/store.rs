use bazel_protos;
use boxfuture::{BoxFuture, Boxable};
use futures::{Future, future};
use hashing::{Digest, Fingerprint};
use protobuf::core::Message;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

use pool::ResettablePool;

const MAX_LOCAL_STORE_SIZE_BYTES: usize = 4 * 1024 * 1024 * 1024;

///
/// A content-addressed store of file contents, and Directories.
///
/// Store keeps content on disk, and can optionally delegate to backfill its on-disk storage by
/// fetching files from a remote server which implements the gRPC bytestream interface
/// (see https://github.com/googleapis/googleapis/blob/master/google/bytestream/bytestream.proto)
/// as specified by the gRPC remote execution interface (see
/// https://github.com/googleapis/googleapis/blob/master/google/devtools/remoteexecution/v1test/)
///
/// In the future, it will gain the ability to write back to the gRPC server, too.
///
#[derive(Clone)]
pub struct Store {
  local: local::ByteStore,
  remote: Option<remote::ByteStore>,
}

// Note that Store doesn't implement ByteStore because it operates at a higher level of abstraction,
// considering Directories as a standalone concept, rather than a buffer of bytes.
// This has the nice property that Directories can be trusted to be valid and canonical.
// We may want to re-visit this if we end up wanting to handle local/remote/merged interchangably.
impl Store {
  ///
  /// Make a store which only uses its local storage.
  ///
  pub fn local_only<P: AsRef<Path>>(path: P, pool: Arc<ResettablePool>) -> Result<Store, String> {
    Ok(Store {
      local: local::ByteStore::new(path, pool)?,
      remote: None,
    })
  }

  ///
  /// Make a store which uses local storage, and if it is missing a value which it tries to load,
  /// will attempt to back-fill its local storage from a remote CAS.
  ///
  pub fn backfills_from_remote<P: AsRef<Path>>(
    path: P,
    pool: Arc<ResettablePool>,
    cas_address: &str,
    thread_count: usize,
    chunk_size_bytes: usize,
    timeout: Duration,
  ) -> Result<Store, String> {
    Ok(Store {
      local: local::ByteStore::new(path, pool)?,
      remote: Some(remote::ByteStore::new(
        cas_address,
        thread_count,
        chunk_size_bytes,
        timeout,
      )),
    })
  }

  pub fn store_file_bytes(&self, bytes: Vec<u8>, initial_lease: bool) -> BoxFuture<Digest, String> {
    self.local.store_bytes(
      EntryType::File,
      bytes,
      initial_lease,
    )
  }

  ///
  /// Loads the bytes of the file with the passed fingerprint, and returns the result of applying f
  /// to that value.
  ///
  pub fn load_file_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
    &self,
    fingerprint: Fingerprint,
    f: F,
  ) -> BoxFuture<Option<T>, String> {
    // No transformation or verification is needed for files, so we pass in a pair of functions
    // which always succeed, whether the underlying bytes are coming from a local or remote store.
    // Unfortunately, we need to be a little verbose to do this.
    let f_local = Arc::new(f);
    let f_remote = f_local.clone();
    self.load_bytes_with(
      EntryType::File,
      fingerprint,
      move |v: &[u8]| Ok(f_local(v)),
      move |v: &[u8]| Ok(f_remote(v)),
    )
  }

  ///
  /// Save the bytes of the Directory proto, without regard for any of the contents of any FileNodes
  /// or DirectoryNodes therein (i.e. does not require that its children are already stored).
  ///
  pub fn record_directory(
    &self,
    directory: &bazel_protos::remote_execution::Directory,
    initial_lease: bool,
  ) -> BoxFuture<Digest, String> {
    let local = self.local.clone();
    future::result(directory.write_to_bytes().map_err(|e| {
      format!("Error serializing directory proto {:?}: {:?}", directory, e)
    })).and_then(move |bytes| {
      local.store_bytes(EntryType::Directory, bytes, initial_lease)
    })
      .to_boxed()
  }

  ///
  /// Guarantees that if an Ok Some value is returned, it is valid, and canonical, and its
  /// fingerprint exactly matches that which is requested. Will return an Err if it would return a
  /// non-canonical Directory.
  ///
  pub fn load_directory(
    &self,
    fingerprint: Fingerprint,
  ) -> BoxFuture<Option<bazel_protos::remote_execution::Directory>, String> {
    let fingerprint_copy = fingerprint.clone();
    let fingerprint_copy2 = fingerprint.clone();
    self.load_bytes_with(
      EntryType::Directory,
      fingerprint.clone(),
      // Trust that locally stored values were canonical when they were written into the CAS,
      // don't bother to check this, as it's slightly expensive.
      move |bytes: &[u8]| {
        let mut directory = bazel_protos::remote_execution::Directory::new();
        directory.merge_from_bytes(bytes).map_err(|e| {
          format!(
            "LMDB corruption: Directory bytes for {} were not valid: {:?}",
            fingerprint_copy,
            e
          )
        })?;
        Ok(directory)
      },
      // Eagerly verify that CAS-returned Directories are canonical, so that we don't write them
      // into our local store.
      move |bytes: &[u8]| {
        let mut directory = bazel_protos::remote_execution::Directory::new();
        directory.merge_from_bytes(bytes).map_err(|e| {
          format!(
            "CAS returned Directory proto for {} which was not valid: {:?}",
            fingerprint_copy2,
            e
          )
        })?;
        bazel_protos::verify_directory_canonical(&directory)?;
        Ok(directory)
      },
    )
  }

  fn load_bytes_with<
    T: Send + 'static,
    FLocal: Fn(&[u8]) -> Result<T, String> + Send + Sync + 'static,
    FRemote: Fn(&[u8]) -> Result<T, String> + Send + Sync + 'static,
  >(
    &self,
    entry_type: EntryType,
    fingerprint: Fingerprint,
    f_local: FLocal,
    f_remote: FRemote,
  ) -> BoxFuture<Option<T>, String> {
    let local = self.local.clone();
    let maybe_remote = self.remote.clone();
    self
      .local
      .load_bytes_with(entry_type, fingerprint.clone(), f_local)
      .and_then(move |maybe_local_value| match (
        maybe_local_value,
        maybe_remote,
      ) {
        (Some(value_result), _) => {
          future::done(value_result.map(|v| Some(v))).to_boxed() as BoxFuture<_, _>
        }
        (None, None) => future::ok(None).to_boxed() as BoxFuture<_, _>,
        (None, Some(remote)) => {
          remote
            .load_bytes_with(
              entry_type,
              fingerprint,
              move |bytes: &[u8]| Vec::from(bytes),
            )
            .and_then(move |maybe_bytes: Option<Vec<u8>>| match maybe_bytes {
              Some(bytes) => {
                future::done(f_remote(&bytes))
                  .and_then(move |value| {
                    local.store_bytes(entry_type, bytes, true).and_then(
                      move |digest| {
                        if digest.0 == fingerprint {
                          Ok(Some(value))
                        } else {
                          Err(format!(
                            "CAS gave wrong fingerprint: expected {}, got {}",
                            fingerprint,
                            digest.0
                          ))
                        }
                      },
                    )
                  })
                  .to_boxed()
              }
              None => future::ok(None).to_boxed() as BoxFuture<_, _>,
            })
            .to_boxed()
        }
      })
      .to_boxed()
  }

  pub fn lease_all<Fs: Iterator<Item = Fingerprint>>(
    &self,
    fingerprints: Fs,
  ) -> Result<(), String> {
    self.local.lease_all(fingerprints)
  }

  pub fn garbage_collect(&self) -> Result<(), String> {
    let target = MAX_LOCAL_STORE_SIZE_BYTES / 2;
    match self.local.shrink(target) {
      Ok(size) => {
        if size > target {
          return Err(format!(
            "Garbage collection attempted to target {} bytes but could only shrink to {} bytes",
            target,
            size
          ));
        }
      }
      Err(err) => return Err(format!("Garbage collection failed: {:?}", err)),
    };
    Ok(())
  }
}

// Only public for testing.
#[derive(Copy, Clone, Eq, PartialEq, Ord, PartialOrd)]
pub enum EntryType {
  Directory,
  File,
}

mod local {
  use super::EntryType;

  use boxfuture::{Boxable, BoxFuture};
  use byteorder::{ByteOrder, LittleEndian};
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::Future;
  use hashing::{Digest, Fingerprint};
  use lmdb::{self, Cursor, Database, DatabaseFlags, Environment, NO_OVERWRITE, RwTransaction,
             Transaction, WriteFlags};
  use lmdb::Error::{KeyExist, MapFull, NotFound};
  use sha2::Sha256;
  use std::collections::BinaryHeap;
  use std::error::Error;
  use std::path::Path;
  use std::sync::Arc;
  use std::time;

  use pool::ResettablePool;
  use super::MAX_LOCAL_STORE_SIZE_BYTES;

  #[derive(Clone)]
  pub struct ByteStore {
    inner: Arc<InnerStore>,
  }

  struct InnerStore {
    env: Environment,
    pool: Arc<ResettablePool>,
    file_database: Database,
    // Store directories separately from files because:
    //  1. They may have different lifetimes.
    //  2. It's nice to know whether we should be able to parse something as a proto.
    directory_database: Database,
    lease_database: Database,
  }

  impl ByteStore {
    pub fn new<P: AsRef<Path>>(path: P, pool: Arc<ResettablePool>) -> Result<ByteStore, String> {
      // 3 DBs; one for file contents, one for directories, one for leases.
      let env = Environment::new()
        .set_max_dbs(3)
        .set_map_size(MAX_LOCAL_STORE_SIZE_BYTES)
        .open(path.as_ref())
        .map_err(|e| format!("Error making env: {:?}", e))?;
      let file_database = env
        .create_db(Some("files"), DatabaseFlags::empty())
        .map_err(|e| {
          format!("Error creating/opening files database: {:?}", e)
        })?;
      let directory_database = env
        .create_db(Some("directories"), DatabaseFlags::empty())
        .map_err(|e| {
          format!("Error creating/opening directories database: {:?}", e)
        })?;
      let lease_database = env
        .create_db(Some("leases"), DatabaseFlags::empty())
        .map_err(|e| {
          format!("Error creating/opening leases database: {:?}", e)
        })?;
      Ok(ByteStore {
        inner: Arc::new(InnerStore {
          env,
          pool,
          file_database,
          directory_database,
          lease_database,
        }),
      })
    }

    pub fn lease_all<Fs: Iterator<Item = Fingerprint>>(
      &self,
      fingerprints: Fs,
    ) -> Result<(), String> {
      self
        .inner
        .env
        .begin_rw_txn()
        .map_err(|err| format!("Error making lmdb transaction: {:?}", err))
        .and_then(|mut txn| {
          let until = Self::default_lease_until_secs_since_epoch();
          for fingerprint in fingerprints {
            self.lease(&fingerprint, until, &mut txn).map_err(|e| {
              format!("Error leasing fingerprint {}: {:?}", fingerprint, e)
            })?;
          }
          Ok(txn)
        })
        .and_then(|txn| {
          txn.commit().map_err(
            |e| format!("Error writing lease: {:?}", e),
          )
        })
    }

    fn default_lease_until_secs_since_epoch() -> u64 {
      let now_since_epoch = time::SystemTime::now()
        .duration_since(time::UNIX_EPOCH)
        .expect("Surely you're not before the unix epoch?");
      (now_since_epoch + time::Duration::from_secs(2 * 60 * 60)).as_secs()
    }

    fn lease(
      &self,
      fingerprint: &Fingerprint,
      until_secs_since_epoch: u64,
      txn: &mut RwTransaction,
    ) -> Result<(), lmdb::Error> {
      let mut buf = [0; 8];
      LittleEndian::write_u64(&mut buf, until_secs_since_epoch);
      txn.put(
        self.inner.lease_database,
        &fingerprint.as_ref(),
        &buf,
        WriteFlags::empty(),
      )
    }

    ///
    /// Attempts to shrink the stored files to be no bigger than target_bytes
    /// (excluding lmdb overhead).
    ///
    /// Returns the size it was shrunk to, which may be larger than target_bytes.
    ///
    /// TODO: Use LMDB database statistics when lmdb-rs exposes them.
    ///
    pub fn shrink(&self, target_bytes: usize) -> Result<usize, String> {
      let mut used_bytes: usize = 0;
      let mut fingerprints_by_expired_ago = BinaryHeap::new();

      self
        .inner
        .env
        .begin_rw_txn()
        .and_then(|mut txn| {
          {
            self.aged_fingerprints(
              &txn,
              EntryType::File,
              &mut used_bytes,
              &mut fingerprints_by_expired_ago,
            );
            self.aged_fingerprints(
              &txn,
              EntryType::Directory,
              &mut used_bytes,
              &mut fingerprints_by_expired_ago,
            );
          }
          while used_bytes > target_bytes {
            let aged_fingerprint = fingerprints_by_expired_ago.pop().expect(
              "lmdb corruption detected, sum of size of blobs exceeded stored blobs",
            );
            if aged_fingerprint.expired_seconds_ago == 0 {
              // Ran out of expired blobs - everything remaining is leased and cannot be collected.
              return Err(MapFull);
            }
            txn
              .del(
                match aged_fingerprint.entry_type {
                  EntryType::File => self.inner.file_database,
                  EntryType::Directory => self.inner.directory_database,
                },
                &aged_fingerprint.fingerprint.as_ref(),
                None,
              )
              .expect("Failed to delete lmdb blob");

            txn
              .del(
                self.inner.lease_database,
                &aged_fingerprint.fingerprint.as_ref(),
                None,
              )
              .or_else(|err| match err {
                NotFound => Ok(()),
                err => Err(err),
              })
              .expect("Failed to delete lmdb lease");
            used_bytes -= aged_fingerprint.size_bytes;
          }
          txn.commit()
        })
        .or_else(|e| match e {
          MapFull => Ok(()),
          e => Err(format!("Error shrinking store: {:?}", e)),
        })?;
      Ok(used_bytes)
    }

    fn aged_fingerprints<T>(
      &self,
      txn: &T,
      entry_type: EntryType,
      used_bytes: &mut usize,
      fingerprints_by_expired_ago: &mut BinaryHeap<AgedFingerprint>,
    ) where
      T: Transaction,
    {
      let database = match entry_type {
        EntryType::File => self.inner.file_database,
        EntryType::Directory => self.inner.directory_database,
      };

      let mut cursor = txn.open_ro_cursor(database).expect(
        "Failed to open lmdb read cursor",
      );
      for (key, bytes) in cursor.iter() {
        *used_bytes = *used_bytes + bytes.len();

        // Random access into the lease_database is slower than iterating, but hopefully garbage
        // collection is rare enough that we can get away with this, rather than do two passes here
        // (either to populate leases into pre-populated AgedFingerprints, or to read sizes when
        // we delete from lmdb to track how much we've freed).
        let lease_until_unix_timestamp = txn
          .get(self.inner.lease_database, &key)
          .map(|b| LittleEndian::read_u64(b))
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

    pub fn store_bytes(
      &self,
      entry_type: EntryType,
      bytes: Vec<u8>,
      initial_lease: bool,
    ) -> BoxFuture<Digest, String> {
      let len = bytes.len();
      let db = match entry_type {
        EntryType::Directory => self.inner.directory_database,
        EntryType::File => self.inner.file_database,
      }.clone();

      let inner = self.inner.clone();
      let bytestore = self.clone();
      self
        .inner
        .pool
        .spawn_fn(move || {
          let fingerprint = {
            let mut hasher = Sha256::default();
            hasher.input(&bytes);
            Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
          };

          let put_res = inner.env.begin_rw_txn().and_then(|mut txn| {
            txn.put(db, &fingerprint, &bytes, NO_OVERWRITE)?;
            if initial_lease {
              bytestore.lease(
                &fingerprint,
                Self::default_lease_until_secs_since_epoch(),
                &mut txn,
              )?;
            }
            txn.commit()
          });

          match put_res {
            Ok(()) => Ok(fingerprint),
            Err(KeyExist) => Ok(fingerprint),
            Err(err) => Err(format!(
              "Error storing fingerprint {}: {:?}",
              fingerprint,
              err
            )),
          }
        })
        .map(move |fingerprint| Digest(fingerprint, len))
        .to_boxed()
    }

    pub fn load_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
      &self,
      entry_type: EntryType,
      fingerprint: Fingerprint,
      f: F,
    ) -> BoxFuture<Option<T>, String> {
      let db = match entry_type {
        EntryType::Directory => self.inner.directory_database,
        EntryType::File => self.inner.file_database,
      }.clone();

      let store = self.inner.clone();
      self
        .inner
        .pool
        .spawn_fn(move || {
          let ro_txn = store.env.begin_ro_txn().map_err(|err| {
            format!(
              "Failed to begin read transaction: {}",
              err.description().to_string()
            )
          });
          ro_txn.and_then(|txn| match txn.get(db, &fingerprint) {
            Ok(bytes) => Ok(Some(f(bytes))),
            Err(NotFound) => Ok(None),
            Err(err) => Err(format!(
              "Error loading fingerprint {}: {}",
              fingerprint,
              err.description().to_string()
            )),
          })
        })
        .to_boxed()
    }
  }

  #[derive(Eq, PartialEq, Ord, PartialOrd)]
  struct AgedFingerprint {
    // expired_seconds_ago must be the first field for the Ord implementation.
    pub expired_seconds_ago: u64,
    pub fingerprint: Fingerprint,
    pub size_bytes: usize,
    pub entry_type: EntryType,
  }

  #[cfg(test)]
  pub mod tests {
    use futures::Future;
    use super::{ByteStore, EntryType, Fingerprint, ResettablePool};
    use lmdb::{DatabaseFlags, Environment, Transaction, WriteFlags};
    use protobuf::Message;
    use std::path::Path;
    use std::sync::Arc;
    use tempdir::TempDir;

    use super::super::tests::{DIRECTORY_HASH, HASH, digest, directory, directory_fingerprint,
                              fingerprint, other_directory, other_directory_fingerprint, str_bytes};

    #[test]
    fn save_file() {
      let dir = TempDir::new("store").unwrap();

      assert_eq!(
        new_store(dir.path())
          .store_bytes(EntryType::File, str_bytes(), false)
          .wait(),
        Ok(digest())
      );
    }

    #[test]
    fn save_file_is_idempotent() {
      let dir = TempDir::new("store").unwrap();

      new_store(dir.path())
        .store_bytes(EntryType::File, str_bytes(), false)
        .wait()
        .unwrap();
      assert_eq!(
        new_store(dir.path())
          .store_bytes(EntryType::File, str_bytes(), false)
          .wait(),
        Ok(digest())
      );
    }

    #[test]
    fn save_file_collision_preserves_first() {
      let dir = TempDir::new("store").unwrap();

      let fingerprint = Fingerprint::from_hex_string(HASH).unwrap();
      let bogus_value: Vec<u8> = vec![];

      let env = Environment::new().set_max_dbs(1).open(dir.path()).unwrap();
      let database = env.create_db(Some("files"), DatabaseFlags::empty());
      env
        .begin_rw_txn()
        .and_then(|mut txn| {
          txn.put(database.unwrap(), &fingerprint, &bogus_value, WriteFlags::empty())
                .and_then(|()| txn.commit())
        })
        .unwrap();

      assert_eq!(
        load_file_bytes(&new_store(dir.path()), fingerprint),
        Ok(Some(bogus_value.clone()))
      );

      assert_eq!(
        new_store(dir.path())
          .store_bytes(EntryType::File, str_bytes(), false)
          .wait(),
        Ok(digest())
      );

      assert_eq!(
        load_file_bytes(&new_store(dir.path()), fingerprint),
        Ok(Some(bogus_value.clone()))
      );
    }

    #[test]
    fn roundtrip_file() {
      let data = str_bytes();
      let dir = TempDir::new("store").unwrap();

      let store = new_store(dir.path());
      let hash = store
        .store_bytes(EntryType::File, data.clone(), false)
        .wait()
        .unwrap();
      assert_eq!(load_file_bytes(&store, hash.0), Ok(Some(data)));
    }

    #[test]
    fn missing_file() {
      let dir = TempDir::new("store").unwrap();
      assert_eq!(
        load_file_bytes(&new_store(dir.path()), fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn record_and_load_directory_proto() {
      let dir = TempDir::new("store").unwrap();

      assert_eq!(
        &new_store(dir.path())
          .store_bytes(
            EntryType::Directory,
            directory().write_to_bytes().unwrap(),
            false,
          )
          .wait()
          .unwrap()
          .0
          .to_hex(),
        DIRECTORY_HASH
      );

      assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), directory_fingerprint()),
        Ok(Some(directory().write_to_bytes().unwrap()))
      );
    }

    #[test]
    fn missing_directory() {
      let dir = TempDir::new("store").unwrap();

      assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), directory_fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn file_is_not_directory_proto() {
      let dir = TempDir::new("store").unwrap();

      new_store(dir.path())
        .store_bytes(EntryType::File, str_bytes(), false)
        .wait()
        .unwrap();

      assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn garbage_collect_nothing_to_do() {
      let dir = TempDir::new("store").unwrap();
      let store = new_store(dir.path());
      let bytes = "0123456789".as_bytes().to_vec();
      store
        .store_bytes(EntryType::File, bytes.clone(), false)
        .wait()
        .expect("Error storing");
      store.shrink(10).expect("Error shrinking");
      assert_eq!(
        load_bytes(
          &store,
          EntryType::File,
          Fingerprint::from_hex_string(
            "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
          ).unwrap(),
        ),
        Ok(Some(bytes))
      );
    }

    #[test]
    fn garbage_collect_nothing_to_do_with_lease() {
      let dir = TempDir::new("store").unwrap();
      let store = new_store(dir.path());
      let bytes = "0123456789".as_bytes().to_vec();
      store
        .store_bytes(EntryType::File, bytes.clone(), false)
        .wait()
        .expect("Error storing");
      let file_fingerprint = Fingerprint::from_hex_string(
        "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
      ).unwrap();
      store.lease_all(vec![file_fingerprint].into_iter()).expect(
        "Error leasing",
      );
      store.shrink(10).expect("Error shrinking");
      assert_eq!(
        load_bytes(&store, EntryType::File, file_fingerprint),
        Ok(Some(bytes))
      );
    }

    #[test]
    fn garbage_collect_remove_one_of_two_files_no_leases() {
      let dir = TempDir::new("store").unwrap();
      let store = new_store(dir.path());
      let bytes_1 = "0123456789".as_bytes().to_vec();
      let fingerprint_1 = Fingerprint::from_hex_string(
        "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
      ).unwrap();
      let bytes_2 = "9876543210".as_bytes().to_vec();
      let fingerprint_2 = Fingerprint::from_hex_string(
        "7619ee8cea49187f309616e30ecf54be072259b43760f1f550a644945d5572f2",
      ).unwrap();
      store
        .store_bytes(EntryType::File, bytes_1.clone(), false)
        .wait()
        .expect("Error storing");
      store
        .store_bytes(EntryType::File, bytes_2.clone(), false)
        .wait()
        .expect("Error storing");
      store.shrink(10).expect("Error shrinking");
      let mut entries = Vec::new();
      entries.push(load_bytes(&store, EntryType::File, fingerprint_1).expect(
        "Error loading bytes",
      ));
      entries.push(load_bytes(&store, EntryType::File, fingerprint_2).expect(
        "Error loading bytes",
      ));
      assert_eq!(
        1,
        entries.iter().filter(|maybe| maybe.is_some()).count(),
        "Want one Some but got: {:?}",
        entries
      );
    }

    #[test]
    fn garbage_collect_remove_both_files_no_leases() {
      let dir = TempDir::new("store").unwrap();
      let store = new_store(dir.path());
      let bytes_1 = "0123456789".as_bytes().to_vec();
      let fingerprint_1 = Fingerprint::from_hex_string(
        "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
      ).unwrap();
      let bytes_2 = "9876543210".as_bytes().to_vec();
      let fingerprint_2 = Fingerprint::from_hex_string(
        "7619ee8cea49187f309616e30ecf54be072259b43760f1f550a644945d5572f2",
      ).unwrap();
      store
        .store_bytes(EntryType::File, bytes_1.clone(), false)
        .wait()
        .expect("Error storing");
      store
        .store_bytes(EntryType::File, bytes_2.clone(), false)
        .wait()
        .expect("Error storing");
      store.shrink(1).expect("Error shrinking");
      assert_eq!(
        load_bytes(&store, EntryType::File, fingerprint_1),
        Ok(None),
        "Should have garbage collected {:?}",
        fingerprint_1
      );
      assert_eq!(
        load_bytes(&store, EntryType::File, fingerprint_2),
        Ok(None),
        "Should have garbage collected {:?}",
        fingerprint_2
      );
    }

    #[test]
    fn garbage_collect_remove_one_of_two_directories_no_leases() {
      let dir = TempDir::new("store").unwrap();
      let store = new_store(dir.path());
      store
        .store_bytes(
          EntryType::Directory,
          directory().write_to_bytes().unwrap(),
          false,
        )
        .wait()
        .expect("Error storing");
      store
        .store_bytes(
          EntryType::Directory,
          other_directory().write_to_bytes().unwrap(),
          false,
        )
        .wait()
        .expect("Error storing");
      store.shrink(80).expect("Error shrinking");
      let mut entries = Vec::new();
      entries.push(
        load_bytes(&store, EntryType::Directory, directory_fingerprint())
          .expect("Error loading bytes"),
      );
      entries.push(
        load_bytes(&store, EntryType::Directory, other_directory_fingerprint())
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
      let dir = TempDir::new("store").unwrap();
      let store = new_store(dir.path());

      let directory_bytes = directory().write_to_bytes().unwrap();
      store
        .store_bytes(EntryType::Directory, directory_bytes.clone(), true)
        .wait()
        .expect("Error storing");

      let file_bytes = "0123456789012345678901234567890123456789\
0123456789012345678901234567890123456789"
        .as_bytes()
        .to_vec();
      let file_fingerprint = Fingerprint::from_hex_string(
        "af1909413b96cbb29927b3a67f3a8879c801a37be383e5f9b31df5fa8d10fa2b",
      ).unwrap();
      store
        .store_bytes(EntryType::File, file_bytes.clone(), false)
        .wait()
        .expect("Error storing");

      store.shrink(80).expect("Error shrinking");

      assert_eq!(
        load_bytes(&store, EntryType::File, file_fingerprint),
        Ok(None),
        "File was present when it should've been garbage collected"
      );
      assert_eq!(
        load_bytes(&store, EntryType::Directory, directory_fingerprint()),
        Ok(Some(directory_bytes)),
        "Directory was missing despite lease"
      );
    }

    #[test]
    fn garbage_collect_remove_file_while_leased_file() {
      let dir = TempDir::new("store").unwrap();
      let store = new_store(dir.path());
      store
        .store_bytes(
          EntryType::Directory,
          directory().write_to_bytes().unwrap(),
          false,
        )
        .wait()
        .expect("Error storing");
      let file_bytes = "0123456789012345678901234567890123456789\
0123456789012345678901234567890123456789"
        .as_bytes()
        .to_vec();
      let file_fingerprint = Fingerprint::from_hex_string(
        "af1909413b96cbb29927b3a67f3a8879c801a37be383e5f9b31df5fa8d10fa2b",
      ).unwrap();
      store
        .store_bytes(EntryType::File, file_bytes.clone(), true)
        .wait()
        .expect("Error storing");

      store.shrink(80).expect("Error shrinking");

      assert_eq!(
        load_bytes(&store, EntryType::File, file_fingerprint),
        Ok(Some(file_bytes)),
        "File was missing despite lease"
      );
      assert_eq!(
        load_bytes(&store, EntryType::Directory, directory_fingerprint()),
        Ok(None),
        "Directory was present when it should've been garbage collected"
      );
    }

    #[test]
    fn garbage_collect_fail_because_too_many_leases() {
      let dir = TempDir::new("store").unwrap();
      let store = new_store(dir.path());
      store
        .store_bytes(
          EntryType::Directory,
          directory().write_to_bytes().unwrap(),
          true,
        )
        .wait()
        .expect("Error storing");
      let file_bytes = "01234567890123456789012345678901234567890\
123456789012345678901234567890123456789"
        .as_bytes()
        .to_vec();
      let file_fingerprint = Fingerprint::from_hex_string(
        "af1909413b96cbb29927b3a67f3a8879c801a37be383e5f9b31df5fa8d10fa2b",
      ).unwrap();
      store
        .store_bytes(EntryType::File, file_bytes.clone(), true)
        .wait()
        .expect("Error storing");

      store
        .store_bytes(EntryType::File, str_bytes(), false)
        .wait()
        .expect("Error storing");

      assert_eq!(store.shrink(80), Ok(160));

      assert_eq!(
        load_bytes(&store, EntryType::File, file_fingerprint),
        Ok(Some(file_bytes)),
        "Leased file should still be present"
      );
      assert_eq!(
        load_bytes(&store, EntryType::Directory, directory_fingerprint()),
        Ok(Some(directory().write_to_bytes().unwrap())),
        "Leased directory should still be present"
      );
      // Whether the unleased file is present is undefined.
    }

    pub fn new_store<P: AsRef<Path>>(dir: P) -> ByteStore {
      ByteStore::new(dir, Arc::new(ResettablePool::new("test-pool-".to_string()))).unwrap()
    }

    pub fn load_file_bytes(
      store: &ByteStore,
      fingerprint: Fingerprint,
    ) -> Result<Option<Vec<u8>>, String> {
      load_bytes(&store, EntryType::File, fingerprint)
    }

    pub fn load_directory_proto_bytes(
      store: &ByteStore,
      fingerprint: Fingerprint,
    ) -> Result<Option<Vec<u8>>, String> {
      load_bytes(&store, EntryType::Directory, fingerprint)
    }

    fn load_bytes(
      store: &ByteStore,
      entry_type: EntryType,
      fingerprint: Fingerprint,
    ) -> Result<Option<Vec<u8>>, String> {
      store
        .load_bytes_with(entry_type, fingerprint, |b| b.to_vec())
        .wait()
    }
  }
}

mod remote {
  use super::EntryType;

  use bazel_protos;
  use boxfuture::{Boxable, BoxFuture};
  use bytes::Bytes;
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::{self, future, Future, Sink, Stream};
  use hashing::{Digest, Fingerprint};
  use grpcio;
  use sha2::Sha256;
  use std::cmp::min;
  use std::sync::Arc;
  use std::time::Duration;

  #[derive(Clone)]
  pub struct ByteStore {
    client: Arc<bazel_protos::bytestream_grpc::ByteStreamClient>,
    env: Arc<grpcio::Environment>,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
  }

  impl ByteStore {
    pub fn new(
      cas_address: &str,
      thread_count: usize,
      chunk_size_bytes: usize,
      upload_timeout: Duration,
    ) -> ByteStore {
      let env = Arc::new(grpcio::Environment::new(thread_count));
      let channel = grpcio::ChannelBuilder::new(env.clone()).connect(cas_address);
      let client = Arc::new(bazel_protos::bytestream_grpc::ByteStreamClient::new(
        channel,
      ));
      ByteStore {
        client,
        env,
        chunk_size_bytes,
        upload_timeout,
      }
    }

    pub fn store_bytes(&self, bytes_vec: Vec<u8>) -> BoxFuture<Digest, String> {
      let bytes = Bytes::from(bytes_vec);
      let mut hasher = Sha256::default();
      hasher.input(&bytes);
      let fingerprint = Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice());
      let len = bytes.len();
      let resource_name = format!(
        "{}/uploads/{}/blobs/{}/{}",
        "",
        "",
        fingerprint,
        bytes.len()
      );
      match self.client.write_opt(
        grpcio::CallOption::default().timeout(
          self.upload_timeout,
        ),
      ) {
        Err(err) => {
          future::err(format!(
            "Error attempting to connect to upload fingerprint {}: {:?}",
            fingerprint,
            err
          )).to_boxed() as BoxFuture<_, _>
        }
        Ok((sender, receiver)) => {
          let chunk_size_bytes = self.chunk_size_bytes;
          let stream =
            futures::stream::unfold::<_, _, futures::future::FutureResult<_, grpcio::Error>, _>(
              0 as usize,
              move |offset| if offset >= bytes.len() {
                None
              } else {
                let mut req = bazel_protos::bytestream::WriteRequest::new();
                req.set_resource_name(resource_name.clone());
                req.set_write_offset(offset as i64);
                let next_offset = min(offset + chunk_size_bytes, bytes.len());
                req.set_finish_write(next_offset == bytes.len());
                req.set_data(bytes.slice(offset, next_offset).to_vec());
                Some(future::ok(
                  ((req, grpcio::WriteFlags::default()), next_offset),
                ))
              },
            );

          future::ok(self.client.clone())
            .join(sender.send_all(stream).map_err(move |e| {
              format!(
                "Error attempting to upload fingerprint {}: {:?}",
                fingerprint,
                e
              )
            }))
            .and_then(move |_| {
              receiver.map_err(move |e| {
                format!(
                  "Error from server when uploading fingerprint {}: {:?}",
                  fingerprint,
                  e
                )
              })
            })
            .and_then(move |received| if received.get_committed_size() !=
              len as i64
            {
              Err(format!(
                "Uploading file with fingerprint {}: want commited size {} but got {}",
                fingerprint,
                len,
                received.get_committed_size()
              ))
            } else {
              Ok(Digest(fingerprint, len))
            })
            .to_boxed()
        }
      }
    }

    pub fn load_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
      &self,
      _entry_type: EntryType,
      fingerprint: Fingerprint,
      f: F,
    ) -> BoxFuture<Option<T>, String> {
      match self.client.read(&{
        let mut req = bazel_protos::bytestream::ReadRequest::new();
        // TODO: Pass a size around, or resolve that we don't need to.
        req.set_resource_name(format!("/blobs/{}/{}", fingerprint, -1));
        req.set_read_offset(0);
        // 0 means no limit.
        req.set_read_limit(0);
        req
      }) {
        Ok(stream) =>
        // We shouldn't have to pass around the client here, it's a workaround for
        // https://github.com/pingcap/grpc-rs/issues/123
        future::ok(self.client.clone())
            .join(stream.map(|r| r.data).concat2())
            .map(|(_client, bytes)| Some(bytes))
            .or_else(|e| match e {
              grpcio::Error::RpcFailure(grpcio::RpcStatus {
                                          status: grpcio::RpcStatusCode::NotFound, ..
                                        }) => Ok(None),
              _ => Err(format!(
                "Error from server in response to CAS read request: {:?}",
                e
              )),
            })
            .map(move |maybe_bytes| {
              maybe_bytes.map(|bytes: Vec<u8>| f(&bytes))
            })
            .to_boxed(),
        Err(err) => future::err(
          format!(
            "Error making CAS read request for {}: {:?}",
            fingerprint,
            err
          )
        ).to_boxed() as BoxFuture<_, _>
      }
    }
  }

  #[cfg(test)]
  mod tests {

    extern crate tempdir;

    use super::{ByteStore, Fingerprint};
    use super::super::EntryType;
    use futures::Future;
    use hashing::Digest;
    use mock::StubCAS;
    use protobuf::Message;
    use std::fs::File;
    use std::io::Read;
    use std::path::PathBuf;
    use std::time::Duration;

    use super::super::tests::{directory, directory_fingerprint, fingerprint, new_cas, str_bytes};

    #[test]
    fn loads_file() {
      let cas = new_cas(10);

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), fingerprint()).unwrap(),
        Some(str_bytes())
      );
    }


    #[test]
    fn missing_file() {
      let cas = StubCAS::empty();

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn load_directory() {
      let cas = new_cas(10);

      assert_eq!(
        load_directory_proto_bytes(&new_byte_store(&cas), directory_fingerprint()),
        Ok(Some(directory().write_to_bytes().unwrap()))
      );
    }

    #[test]
    fn missing_directory() {
      let cas = StubCAS::empty();

      assert_eq!(
        load_directory_proto_bytes(&new_byte_store(&cas), directory_fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn load_file_grpc_error() {
      let cas = StubCAS::always_errors();

      let error = load_file_bytes(&new_byte_store(&cas), fingerprint()).expect_err("Want error");
      assert!(
        error.contains("StubCAS is configured to always fail"),
        format!("Bad error message, got: {}", error)
      )
    }

    #[test]
    fn load_directory_grpc_error() {
      let cas = StubCAS::always_errors();

      let error = load_directory_proto_bytes(&new_byte_store(&cas), directory_fingerprint())
        .expect_err("Want error");
      assert!(
        error.contains("StubCAS is configured to always fail"),
        format!("Bad error message, got: {}", error)
      )
    }

    #[test]
    fn fetch_less_than_one_chunk() {
      let cas = new_cas(str_bytes().len() + 1);

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), fingerprint()),
        Ok(Some(str_bytes()))
      )
    }

    #[test]
    fn fetch_exactly_one_chunk() {
      let cas = new_cas(str_bytes().len());

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), fingerprint()),
        Ok(Some(str_bytes()))
      )
    }

    #[test]
    fn fetch_multiple_chunks_exact() {
      let cas = new_cas(1);

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), fingerprint()),
        Ok(Some(str_bytes()))
      )
    }

    #[test]
    fn fetch_multiple_chunks_nonfactor() {
      let cas = new_cas(9);

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), fingerprint()),
        Ok(Some(str_bytes()))
      )
    }

    #[test]
    fn write_file_one_chunk() {
      let cas = StubCAS::empty();

      let store = new_byte_store(&cas);
      assert_eq!(
        store.store_bytes(str_bytes()).wait(),
        Ok(Digest(fingerprint(), str_bytes().len()))
      );

      let blobs = cas.blobs.lock().unwrap();
      assert_eq!(blobs.get(&fingerprint()), Some(&str_bytes()));
    }

    #[test]
    fn write_file_multiple_chunks() {
      let cas = StubCAS::empty();

      let store = ByteStore::new(&cas.address(), 1, 10 * 1024, Duration::from_secs(1));

      let all_the_henries = {
        let mut f = File::open(
          PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("testdata")
            .join("all_the_henries"),
        ).expect("Error opening all_the_henries");
        let mut bytes = Vec::new();
        f.read_to_end(&mut bytes).expect(
          "Error reading all_the_henries",
        );
        bytes
      };

      let fingerprint = Fingerprint::from_hex_string(
        "8dfba0adc29389c63062a68d76b2309b9a2486f1ab610c4720beabbdc273301f",
      ).unwrap();

      assert_eq!(
        store.store_bytes(all_the_henries.clone()).wait(),
        Ok(Digest(fingerprint, all_the_henries.len()))
      );

      let blobs = cas.blobs.lock().unwrap();
      assert_eq!(blobs.get(&fingerprint), Some(&all_the_henries));

      let write_message_sizes = cas.write_message_sizes.lock().unwrap();
      assert_eq!(
        write_message_sizes.len(),
        98,
        "Wrong number of chunks uploaded"
      );
      for size in write_message_sizes.iter() {
        assert!(
          size <= &(10 * 1024),
          format!("Size {} should have been <= {}", size, 10 * 1024)
        );
      }
    }

    #[test]
    fn write_file_errors() {
      let cas = StubCAS::always_errors();

      let store = new_byte_store(&cas);
      let error = store.store_bytes(str_bytes()).wait().expect_err(
        "Want error",
      );
      assert!(
        error.contains("Error from server"),
        format!("Bad error message, got: {}", error)
      );
      assert!(
        error.contains("StubCAS is configured to always fail"),
        format!("Bad error message, got: {}", error)
      );
    }

    #[test]
    fn write_connection_error() {
      let store = ByteStore::new(
        "doesnotexist.example",
        1,
        10 * 1024 * 1024,
        Duration::from_secs(1),
      );
      let error = store.store_bytes(str_bytes()).wait().expect_err(
        "Want error",
      );
      assert!(
        error.contains("Error attempting to upload fingerprint"),
        format!("Bad error message, got: {}", error)
      );
    }

    fn new_byte_store(cas: &StubCAS) -> ByteStore {
      ByteStore::new(&cas.address(), 1, 10 * 1024 * 1024, Duration::from_secs(1))
    }

    pub fn load_file_bytes(
      store: &ByteStore,
      fingerprint: Fingerprint,
    ) -> Result<Option<Vec<u8>>, String> {
      load_bytes(&store, EntryType::File, fingerprint)
    }

    pub fn load_directory_proto_bytes(
      store: &ByteStore,
      fingerprint: Fingerprint,
    ) -> Result<Option<Vec<u8>>, String> {
      load_bytes(&store, EntryType::Directory, fingerprint)
    }

    fn load_bytes(
      store: &ByteStore,
      entry_type: EntryType,
      fingerprint: Fingerprint,
    ) -> Result<Option<Vec<u8>>, String> {
      store
        .load_bytes_with(entry_type, fingerprint, |b| b.to_vec())
        .wait()
    }
  }
}

#[cfg(test)]
mod tests {
  use super::{EntryType, Store, local};

  use bazel_protos;
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::Future;
  use hashing::{Digest, Fingerprint};
  use mock::StubCAS;
  use pool::ResettablePool;
  use protobuf::Message;
  use sha2::Sha256;
  use std::path::Path;
  use std::sync::Arc;
  use std::time::Duration;
  use tempdir::TempDir;

  pub const STR: &str = "European Burmese";
  pub const HASH: &str = "693d8db7b05e99c6b7a7c0616456039d89c555029026936248085193559a0b5d";
  pub const DIRECTORY_HASH: &str = "63949aa823baf765eff07b946050d76e\
c0033144c785a94d3ebd82baa931cd16";
  pub const OTHER_DIRECTORY_HASH: &str = "1b9357331e7df1f6efb50fe0b15ecb2b\
ca58002b3fa97478e7c2c97640e72ee1";
  const EMPTY_DIRECTORY_HASH: &str = "e3b0c44298fc1c149afbf4c8996fb924\
27ae41e4649b934ca495991b7852b855";

  pub fn fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string(HASH).unwrap()
  }

  pub fn digest() -> Digest {
    Digest(fingerprint(), STR.len())
  }

  pub fn str_bytes() -> Vec<u8> {
    STR.as_bytes().to_owned()
  }

  pub fn directory() -> bazel_protos::remote_execution::Directory {
    make_directory("roland")
  }

  pub fn other_directory() -> bazel_protos::remote_execution::Directory {
    make_directory("dnalor")
  }

  pub fn make_directory(file_name: &str) -> bazel_protos::remote_execution::Directory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name(file_name.to_string());
      file.set_digest({
        let mut digest = bazel_protos::remote_execution::Digest::new();
        digest.set_hash(HASH.to_string());
        digest.set_size_bytes(STR.len() as i64);
        digest
      });
      file.set_is_executable(false);
      file
    });
    directory
  }

  pub fn directory_fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string(DIRECTORY_HASH).unwrap()
  }

  pub fn other_directory_fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string(OTHER_DIRECTORY_HASH).unwrap()
  }

  pub fn load_file_bytes(
    store: &Store,
    fingerprint: Fingerprint,
  ) -> Result<Option<Vec<u8>>, String> {
    store
      .load_file_bytes_with(fingerprint, |bytes: &[u8]| bytes.to_vec())
      .wait()
  }

  pub fn new_cas(chunk_size_bytes: usize) -> StubCAS {
    StubCAS::new(
      chunk_size_bytes as i64,
      vec![
        (fingerprint(), str_bytes()),
        (
          directory_fingerprint(),
          directory().write_to_bytes().unwrap()
        ),
      ].into_iter()
        .collect(),
    )
  }

  fn new_store<P: AsRef<Path>>(dir: P, cas_address: String) -> Store {
    Store::backfills_from_remote(
      dir,
      Arc::new(ResettablePool::new("test-pool-".to_string())),
      &cas_address,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
    ).unwrap()
  }

  #[test]
  fn load_file_prefers_local() {
    let dir = TempDir::new("store").unwrap();

    local::tests::new_store(dir.path())
      .store_bytes(EntryType::File, str_bytes(), false)
      .wait()
      .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
      load_file_bytes(&new_store(dir.path(), cas.address()), fingerprint()),
      Ok(Some(str_bytes()))
    );
    assert_eq!(0, cas.read_request_count());
  }

  #[test]
  fn load_directory_prefers_local() {
    let dir = TempDir::new("store").unwrap();

    local::tests::new_store(dir.path())
      .store_bytes(
        EntryType::Directory,
        directory().write_to_bytes().unwrap(),
        false,
      )
      .wait()
      .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_directory(directory_fingerprint())
        .wait(),
      Ok(Some(directory()))
    );
    assert_eq!(0, cas.read_request_count());
  }

  #[test]
  fn load_file_falls_back_and_backfills() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(1024);
    assert_eq!(
      load_file_bytes(&new_store(dir.path(), cas.address()), fingerprint()),
      Ok(Some(str_bytes())),
      "Read from CAS"
    );
    assert_eq!(1, cas.read_request_count());
    assert_eq!(
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), fingerprint()),
      Ok(Some(str_bytes())),
      "Read from local cache"
    );
  }

  #[test]
  fn load_directory_falls_back_and_backfills() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(1024);
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_directory(directory_fingerprint())
        .wait(),
      Ok(Some(directory()))
    );
    assert_eq!(1, cas.read_request_count());
    assert_eq!(
      local::tests::load_directory_proto_bytes(
        &local::tests::new_store(dir.path()),
        directory_fingerprint(),
      ),
      Ok(Some(directory().write_to_bytes().unwrap()))
    );
  }

  #[test]
  fn load_file_missing_is_none() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::empty();
    assert_eq!(
      load_file_bytes(&new_store(dir.path(), cas.address()), fingerprint()),
      Ok(None)
    );
    assert_eq!(1, cas.read_request_count());
  }

  #[test]
  fn load_directory_missing_is_none() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::empty();
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_directory(directory_fingerprint())
        .wait(),
      Ok(None)
    );
    assert_eq!(1, cas.read_request_count());
  }


  #[test]
  fn load_file_remote_error_is_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::always_errors();
    let error = load_file_bytes(&new_store(dir.path(), cas.address()), fingerprint())
      .expect_err("Want error");
    assert_eq!(1, cas.read_request_count());
    assert!(
      error.contains("StubCAS is configured to always fail"),
      "Bad error message"
    );
  }

  #[test]
  fn load_directory_remote_error_is_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::always_errors();
    let error = new_store(dir.path(), cas.address())
      .load_directory(fingerprint())
      .wait()
      .expect_err("Want error");
    assert_eq!(1, cas.read_request_count());
    assert!(
      error.contains("StubCAS is configured to always fail"),
      "Bad error message"
    );
  }

  #[test]
  fn malformed_remote_directory_is_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(1024);
    new_store(dir.path(), cas.address())
      .load_directory(fingerprint())
      .wait()
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_directory_proto_bytes(&local::tests::new_store(dir.path()), fingerprint()),
      Ok(None)
    );
  }

  #[test]
  fn non_canonical_remote_directory_is_error() {
    let mut directory = directory();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("roland".to_string());
      file.set_digest({
        let mut digest = bazel_protos::remote_execution::Digest::new();
        digest.set_hash(HASH.to_string());
        digest.set_size_bytes(STR.len() as i64);
        digest
      });
      file
    });
    let directory_bytes = directory.write_to_bytes().unwrap();
    let directory_fingerprint = {
      let mut hasher = Sha256::default();
      hasher.input(&directory_bytes);
      Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
    };

    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::new(
      1024,
      vec![(directory_fingerprint.clone(), directory_bytes.clone())]
        .into_iter()
        .collect(),
    );
    new_store(dir.path(), cas.address())
      .load_directory(directory_fingerprint.clone())
      .wait()
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_directory_proto_bytes(
        &local::tests::new_store(dir.path()),
        directory_fingerprint,
      ),
      Ok(None)
    );
  }

  #[test]
  fn wrong_remote_file_bytes_is_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::new(
      1024,
      vec![(fingerprint(), directory().write_to_bytes().unwrap())]
        .into_iter()
        .collect(),
    );
    load_file_bytes(&new_store(dir.path(), cas.address()), fingerprint()).expect_err("Want error");

    assert_eq!(
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), fingerprint()),
      Ok(None)
    );
  }

  #[test]
  fn wrong_remote_directory_bytes_is_error() {
    let dir = TempDir::new("store").unwrap();
    let empty_fingerprint = Fingerprint::from_hex_string(EMPTY_DIRECTORY_HASH).unwrap();

    let cas = StubCAS::new(
      1024,
      vec![(empty_fingerprint, directory().write_to_bytes().unwrap())]
        .into_iter()
        .collect(),
    );
    load_file_bytes(&new_store(dir.path(), cas.address()), empty_fingerprint)
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), empty_fingerprint),
      Ok(None)
    );
  }
}
