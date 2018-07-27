use FileContent;

use bazel_protos;
use boxfuture::{BoxFuture, Boxable};
use bytes::Bytes;
use futures::{future, Future};
use hashing::Digest;
use protobuf::Message;
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use pool::ResettablePool;

// This is the maximum size any particular local LMDB store file is allowed to grow to.
// It doesn't reflect space allocated on disk, or RAM allocated (it may be reflected in VIRT but
// not RSS). There is no practical upper bound on this number, so we set it ridiculously high.
const MAX_LOCAL_STORE_SIZE_BYTES: usize = 1024 * 1024 * 1024 * 1024 / 10;

// This is the target number of bytes which should be present in all combined LMDB store files
// after garbage collection. We almost certainly want to make this configurable.
const LOCAL_STORE_GC_TARGET_BYTES: usize = 4 * 1024 * 1024 * 1024;

///
/// A content-addressed store of file contents, and Directories.
///
/// Store keeps content on disk, and can optionally delegate to backfill its on-disk storage by
/// fetching files from a remote server which implements the gRPC bytestream interface
/// (see https://github.com/googleapis/googleapis/blob/master/google/bytestream/bytestream.proto)
/// as specified by the gRPC remote execution interface (see
/// https://github.com/googleapis/googleapis/blob/master/google/devtools/remoteexecution/v1test/)
///
/// It can also write back to a remote gRPC server, but will only do so when explicitly instructed
/// to do so.
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
  pub fn with_remote<P: AsRef<Path>>(
    path: P,
    pool: Arc<ResettablePool>,
    cas_address: String,
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

  ///
  /// LMDB Environments aren't safe to be re-used after forking, so we need to drop them before
  /// forking and re-create them afterwards.
  ///
  /// I haven't delved into the exact details as to what's fork-unsafe about LMDB, but if two pants
  /// processes run using the same daemon, one takes out some kind of lock which the other cannot
  /// ever acquire, so lmdb returns EAGAIN whenever a transaction is created in the second process.
  ///
  pub fn reset_prefork(&self) {
    self.local.reset_prefork();
    if let Some(ref remote) = self.remote {
      remote.reset_threadpool();
    }
  }

  pub fn store_file_bytes(&self, bytes: Bytes, initial_lease: bool) -> BoxFuture<Digest, String> {
    let len = bytes.len();
    self
      .local
      .store_bytes(EntryType::File, bytes, initial_lease)
      .map(move |fingerprint| Digest(fingerprint, len))
      .to_boxed()
  }

  ///
  /// Loads the bytes of the file with the passed fingerprint, and returns the result of applying f
  /// to that value.
  ///
  pub fn load_file_bytes_with<T: Send + 'static, F: Fn(Bytes) -> T + Send + Sync + 'static>(
    &self,
    digest: Digest,
    f: F,
  ) -> BoxFuture<Option<T>, String> {
    // No transformation or verification is needed for files, so we pass in a pair of functions
    // which always succeed, whether the underlying bytes are coming from a local or remote store.
    // Unfortunately, we need to be a little verbose to do this.
    let f_local = Arc::new(f);
    let f_remote = f_local.clone();
    self.load_bytes_with(
      EntryType::File,
      digest,
      move |v: Bytes| Ok(f_local(v)),
      move |v: Bytes| Ok(f_remote(v)),
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
    future::result(
      directory
        .write_to_bytes()
        .map_err(|e| format!("Error serializing directory proto {:?}: {:?}", directory, e)),
    ).and_then(move |bytes| {
      let len = bytes.len();
      local
        .store_bytes(EntryType::Directory, Bytes::from(bytes), initial_lease)
        .map(move |fingerprint| Digest(fingerprint, len))
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
    digest: Digest,
  ) -> BoxFuture<Option<bazel_protos::remote_execution::Directory>, String> {
    self.load_bytes_with(
      EntryType::Directory,
      digest,
      // Trust that locally stored values were canonical when they were written into the CAS,
      // don't bother to check this, as it's slightly expensive.
      move |bytes: Bytes| {
        let mut directory = bazel_protos::remote_execution::Directory::new();
        directory.merge_from_bytes(&bytes).map_err(|e| {
          format!(
            "LMDB corruption: Directory bytes for {:?} were not valid: {:?}",
            digest, e
          )
        })?;
        Ok(directory)
      },
      // Eagerly verify that CAS-returned Directories are canonical, so that we don't write them
      // into our local store.
      move |bytes: Bytes| {
        let mut directory = bazel_protos::remote_execution::Directory::new();
        directory.merge_from_bytes(&bytes).map_err(|e| {
          format!(
            "CAS returned Directory proto for {:?} which was not valid: {:?}",
            digest, e
          )
        })?;
        bazel_protos::verify_directory_canonical(&directory)?;
        Ok(directory)
      },
    )
  }

  fn load_bytes_with<
    T: Send + 'static,
    FLocal: Fn(Bytes) -> Result<T, String> + Send + Sync + 'static,
    FRemote: Fn(Bytes) -> Result<T, String> + Send + Sync + 'static,
  >(
    &self,
    entry_type: EntryType,
    digest: Digest,
    f_local: FLocal,
    f_remote: FRemote,
  ) -> BoxFuture<Option<T>, String> {
    let local = self.local.clone();
    let maybe_remote = self.remote.clone();
    self
      .local
      .load_bytes_with(entry_type, digest.0, f_local)
      .and_then(
        move |maybe_local_value| match (maybe_local_value, maybe_remote) {
          (Some(value_result), _) => future::done(value_result.map(Some)).to_boxed(),
          (None, None) => future::ok(None).to_boxed(),
          (None, Some(remote)) => remote
            .load_bytes_with(entry_type, digest, move |bytes: Bytes| bytes)
            .and_then(move |maybe_bytes: Option<Bytes>| match maybe_bytes {
              Some(bytes) => future::done(f_remote(bytes.clone()))
                .and_then(move |value| {
                  let len = bytes.len();
                  local
                    .store_bytes(entry_type, bytes, true)
                    .and_then(move |stored_fingerprint| {
                      let stored_digest = Digest(stored_fingerprint, len);
                      if digest == stored_digest {
                        Ok(Some(value))
                      } else {
                        Err(format!(
                          "CAS gave wrong digest: expected {:?}, got {:?}",
                          digest, stored_digest
                        ))
                      }
                    })
                })
                .to_boxed(),
              None => future::ok(None).to_boxed(),
            })
            .to_boxed(),
        },
      )
      .to_boxed()
  }

  ///
  /// Ensures that the remote ByteStore has a copy of each passed Fingerprint, including any files
  /// contained in any Directories in the list.
  ///
  pub fn ensure_remote_has_recursive(&self, digests: Vec<Digest>) -> BoxFuture<(), String> {
    let remote = match self.remote {
      Some(ref remote) => remote,
      None => {
        return future::err("Cannot ensure remote has blobs without a remote".to_owned()).to_boxed()
      }
    };

    let mut expanding_futures = Vec::new();

    let mut expanded_digests = HashMap::new();
    for digest in digests {
      match self.local.entry_type(&digest.0) {
        Ok(Some(EntryType::File)) => {
          expanded_digests.insert(digest, EntryType::File);
        }
        Ok(Some(EntryType::Directory)) => {
          expanding_futures.push(self.expand_directory(digest));
        }
        Ok(None) => {
          return future::err(format!("Failed to upload digest {:?}: Not found", digest)).to_boxed()
        }
        Err(err) => {
          return future::err(format!("Failed to upload digest {:?}: {:?}", digest, err)).to_boxed()
        }
      };
    }

    let local = self.local.clone();
    let remote = remote.clone();
    let remote2 = remote.clone();
    future::join_all(expanding_futures)
      .map(move |futures| {
        for mut digests in futures {
          for (digest, entry_type) in digests.drain() {
            expanded_digests.insert(digest, entry_type);
          }
        }
        expanded_digests
      })
      .and_then(move |digests| {
        if Store::upload_is_faster_than_checking_whether_to_upload(&digests) {
          return Ok((digests.keys().cloned().collect(), digests));
        }
        remote
          .list_missing_digests(digests.keys())
          .map(|filtered_digests| (filtered_digests, digests))
      })
      .and_then(move |(filtered_digests, digest_entry_types)| {
        future::join_all(
          filtered_digests
            .into_iter()
            .map(move |digest| {
              let entry_type = digest_entry_types[&digest];
              let remote = remote2.clone();
              local
                .load_bytes_with(entry_type.clone(), digest.0, move |bytes| {
                  remote.store_bytes(bytes)
                })
                .and_then(move |maybe_future| match maybe_future {
                  Some(future) => Ok(future),
                  None => Err(format!("Failed to upload digest {:?}: Not found", digest)),
                })
            })
            .collect::<Vec<_>>(),
        )
      })
      .and_then(future::join_all)
      .map(|_| ())
      .to_boxed()
  }

  pub fn lease_all<'a, Ds: Iterator<Item = &'a Digest>>(&self, digests: Ds) -> Result<(), String> {
    self.local.lease_all(digests)
  }

  pub fn garbage_collect(&self) -> Result<(), String> {
    let target = LOCAL_STORE_GC_TARGET_BYTES;
    match self.local.shrink(target) {
      Ok(size) => {
        if size > target {
          return Err(format!(
            "Garbage collection attempted to target {} bytes but could only shrink to {} bytes",
            target, size
          ));
        }
      }
      Err(err) => return Err(format!("Garbage collection failed: {:?}", err)),
    };
    Ok(())
  }

  ///
  /// To check if it might be faster to upload the digests recursively
  /// vs checking if the files are present first.
  ///
  /// The values are guesses, feel free to tweak them.
  ///
  fn upload_is_faster_than_checking_whether_to_upload(
    digests: &HashMap<Digest, EntryType>,
  ) -> bool {
    if digests.len() < 3 {
      let mut num_bytes = 0;
      for digest in digests.keys() {
        num_bytes += digest.1;
      }
      num_bytes < 1024 * 1024
    } else {
      false
    }
  }

  pub fn expand_directory(&self, digest: Digest) -> BoxFuture<HashMap<Digest, EntryType>, String> {
    let accumulator = Arc::new(Mutex::new(HashMap::new()));

    self
      .expand_directory_helper(digest, accumulator.clone())
      .map(|()| {
        Arc::try_unwrap(accumulator)
          .expect("Arc should have been unwrappable")
          .into_inner()
          .unwrap()
      })
      .to_boxed()
  }

  fn expand_directory_helper(
    &self,
    digest: Digest,
    accumulator: Arc<Mutex<HashMap<Digest, EntryType>>>,
  ) -> BoxFuture<(), String> {
    let store = self.clone();
    self
      .load_directory(digest)
      .and_then(move |maybe_directory| match maybe_directory {
        Some(directory) => {
          {
            let mut accumulator = accumulator.lock().unwrap();
            accumulator.insert(digest, EntryType::Directory);
            for file in directory.get_files() {
              accumulator.insert(try_future!(file.get_digest().into()), EntryType::File);
            }
          }
          future::join_all(
            directory
              .get_directories()
              .into_iter()
              .map(move |subdir| {
                store.clone().expand_directory_helper(
                  try_future!(subdir.get_digest().into()),
                  accumulator.clone(),
                )
              })
              .collect::<Vec<_>>(),
          ).map(|_| ())
            .to_boxed()
        }
        None => future::err(format!("Could not expand unknown directory: {:?}", digest)).to_boxed(),
      })
      .to_boxed()
  }

  pub fn materialize_directory(
    &self,
    destination: PathBuf,
    digest: Digest,
  ) -> BoxFuture<(), String> {
    match super::safe_create_dir_all(&destination) {
      Ok(()) => {}
      Err(e) => return future::err(e).to_boxed(),
    };
    let store = self.clone();
    self
      .load_directory(digest)
      .and_then(move |directory_opt| {
        directory_opt.ok_or_else(|| format!("Directory with digest {:?} not found", digest))
      })
      .and_then(move |directory| {
        let file_futures = directory
          .get_files()
          .iter()
          .map(|file_node| {
            let store = store.clone();
            let path = destination.join(file_node.get_name());
            let digest = try_future!(file_node.get_digest().into());
            store.materialize_file(path, digest, file_node.is_executable)
          })
          .collect::<Vec<_>>();
        let directory_futures = directory
          .get_directories()
          .iter()
          .map(|directory_node| {
            let store = store.clone();
            let path = destination.join(directory_node.get_name());
            let digest = try_future!(directory_node.get_digest().into());
            store.materialize_directory(path, digest)
          })
          .collect::<Vec<_>>();
        future::join_all(file_futures)
          .join(future::join_all(directory_futures))
          .map(|_| ())
      })
      .to_boxed()
  }

  fn materialize_file(
    &self,
    destination: PathBuf,
    digest: Digest,
    is_executable: bool,
  ) -> BoxFuture<(), String> {
    self
      .load_file_bytes_with(digest, move |bytes| {
        OpenOptions::new()
          .create(true)
          .write(true)
          .mode(if is_executable { 0o755 } else { 0o644 })
          .open(&destination)
          .and_then(|mut f| f.write_all(&bytes))
          .map_err(|e| format!("Error writing file {:?}: {:?}", destination, e))
      })
      .and_then(move |write_result| match write_result {
        Some(Ok(())) => Ok(()),
        Some(Err(e)) => Err(e),
        None => Err(format!("File with digest {:?} not found", digest)),
      })
      .to_boxed()
  }

  // Returns files sorted by their path.
  pub fn contents_for_directory(
    &self,
    directory: &bazel_protos::remote_execution::Directory,
  ) -> BoxFuture<Vec<FileContent>, String> {
    let accumulator = Arc::new(Mutex::new(HashMap::new()));
    self
      .contents_for_directory_helper(directory, PathBuf::new(), accumulator.clone())
      .map(|()| {
        let map = Arc::try_unwrap(accumulator).unwrap().into_inner().unwrap();
        let mut vec: Vec<FileContent> = map
          .into_iter()
          .map(|(path, content)| FileContent { path, content })
          .collect();
        vec.sort_by(|l, r| l.path.cmp(&r.path));
        vec
      })
      .to_boxed()
  }

  // Assumes that all fingerprints it encounters are valid.
  fn contents_for_directory_helper(
    &self,
    directory: &bazel_protos::remote_execution::Directory,
    path_so_far: PathBuf,
    contents_wrapped: Arc<Mutex<HashMap<PathBuf, Bytes>>>,
  ) -> BoxFuture<(), String> {
    let contents_wrapped_copy = contents_wrapped.clone();
    let path_so_far_copy = path_so_far.clone();
    let store_copy = self.clone();
    let file_futures = future::join_all(
      directory
        .get_files()
        .iter()
        .map(move |file_node| {
          let path = path_so_far_copy.join(file_node.get_name());
          let contents_wrapped_copy = contents_wrapped_copy.clone();
          store_copy
            .load_file_bytes_with(try_future!(file_node.get_digest().into()), |b| b)
            .and_then(move |maybe_bytes| {
              maybe_bytes
                .ok_or_else(|| format!("Couldn't find file contents for {:?}", path))
                .map(move |bytes| {
                  let mut contents = contents_wrapped_copy.lock().unwrap();
                  contents.insert(path, bytes);
                })
            })
            .to_boxed()
        })
        .collect::<Vec<_>>(),
    );
    let store = self.clone();
    let dir_futures = future::join_all(
      directory
        .get_directories()
        .into_iter()
        .map(move |dir_node| {
          let digest = try_future!(dir_node.get_digest().into());
          let path = path_so_far.join(dir_node.get_name());
          let store = store.clone();
          let contents_wrapped = contents_wrapped.clone();
          store
            .load_directory(digest)
            .and_then(move |maybe_dir| {
              maybe_dir
                .ok_or_else(|| format!("Could not find sub-directory with digest {:?}", digest))
            })
            .and_then(move |dir| store.contents_for_directory_helper(&dir, path, contents_wrapped))
            .to_boxed()
        })
        .collect::<Vec<_>>(),
    );
    file_futures.join(dir_futures).map(|(_, _)| ()).to_boxed()
  }
}

// Only public for testing.
#[derive(Copy, Clone, Debug, Eq, Hash, PartialEq, Ord, PartialOrd)]
pub enum EntryType {
  Directory,
  File,
}

mod local {
  use super::EntryType;

  use boxfuture::{BoxFuture, Boxable};
  use byteorder::{ByteOrder, LittleEndian};
  use bytes::Bytes;
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::future;
  use hashing::{Digest, Fingerprint};
  use lmdb::Error::{KeyExist, NotFound};
  use lmdb::{
    self, Cursor, Database, DatabaseFlags, Environment, RwTransaction, Transaction, WriteFlags,
    NO_OVERWRITE, NO_SYNC, NO_TLS,
  };
  use resettable::Resettable;
  use sha2::Sha256;
  use std::collections::{BinaryHeap, HashMap};
  use std::fmt;
  use std::path::Path;
  use std::sync::Arc;
  use std::time;

  use super::super::EMPTY_FINGERPRINT;
  use super::MAX_LOCAL_STORE_SIZE_BYTES;
  use pool::ResettablePool;

  #[derive(Clone)]
  pub struct ByteStore {
    inner: Arc<InnerStore>,
  }

  struct InnerStore {
    pool: Arc<ResettablePool>,
    // Store directories separately from files because:
    //  1. They may have different lifetimes.
    //  2. It's nice to know whether we should be able to parse something as a proto.
    file_dbs: Resettable<Result<Arc<ShardedLmdb>, String>>,
    directory_dbs: Resettable<Result<Arc<ShardedLmdb>, String>>,
  }

  impl ByteStore {
    pub fn new<P: AsRef<Path>>(path: P, pool: Arc<ResettablePool>) -> Result<ByteStore, String> {
      let root = path.as_ref();
      let files_root = root.join("files");
      let directories_root = root.join("directories");
      Ok(ByteStore {
        inner: Arc::new(InnerStore {
          pool: pool,
          file_dbs: Resettable::new(move || ShardedLmdb::new(&files_root).map(Arc::new)),
          directory_dbs: Resettable::new(move || ShardedLmdb::new(&directories_root).map(Arc::new)),
        }),
      })
    }

    pub fn reset_prefork(&self) {
      self.inner.file_dbs.reset();
      self.inner.directory_dbs.reset();
    }

    // Note: This performs IO on the calling thread. Hopefully the IO is small enough not to matter.
    pub fn entry_type(&self, fingerprint: &Fingerprint) -> Result<Option<EntryType>, String> {
      {
        let (env, directory_database, _) = self.inner.directory_dbs.get()?.get(fingerprint);
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
            ))
          }
        };
      }
      let (env, file_database, _) = self.inner.file_dbs.get()?.get(fingerprint);
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
          ))
        }
      };
      Ok(None)
    }

    pub fn lease_all<'a, Ds: Iterator<Item = &'a Digest>>(
      &self,
      digests: Ds,
    ) -> Result<(), String> {
      let until = Self::default_lease_until_secs_since_epoch();
      for digest in digests {
        let (env, _, lease_database) = self.inner.file_dbs.get()?.get(&digest.0);
        env
          .begin_rw_txn()
          .and_then(|mut txn| self.lease(&lease_database, &digest.0, until, &mut txn))
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
      database: &Database,
      fingerprint: &Fingerprint,
      until_secs_since_epoch: u64,
      txn: &mut RwTransaction,
    ) -> Result<(), lmdb::Error> {
      let mut buf = [0; 8];
      LittleEndian::write_u64(&mut buf, until_secs_since_epoch);
      txn.put(*database, &fingerprint.as_ref(), &buf, WriteFlags::empty())
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
    pub fn shrink(&self, target_bytes: usize) -> Result<usize, String> {
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
        let (env, database, lease_database) = lmdbs.get()?.get(&aged_fingerprint.fingerprint);
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

      for &(ref env, ref database, ref lease_database) in &database.get()?.all_lmdbs() {
        let txn = env
          .begin_ro_txn()
          .map_err(|err| format!("Error beginning transaction to garbage collect: {}", err))?;
        let mut cursor = txn
          .open_ro_cursor(*database)
          .map_err(|err| format!("Failed to open lmdb read cursor: {}", err))?;
        for (key, bytes) in cursor.iter() {
          *used_bytes = *used_bytes + bytes.len();

          // Random access into the lease_database is slower than iterating, but hopefully garbage
          // collection is rare enough that we can get away with this, rather than do two passes
          // here (either to populate leases into pre-populated AgedFingerprints, or to read sizes
          // when we delete from lmdb to track how much we've freed).
          let lease_until_unix_timestamp = txn
            .get(*lease_database, &key)
            .map(|b| LittleEndian::read_u64(b))
            .unwrap_or_else(|e| match e {
              NotFound => 0,
              e => panic!("Error reading lease, probable lmdb corruption: {:?}", e),
            });

          let leased_until =
            time::UNIX_EPOCH + time::Duration::from_secs(lease_until_unix_timestamp);

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
    ) -> BoxFuture<Fingerprint, String> {
      let dbs = match entry_type {
        EntryType::Directory => self.inner.directory_dbs.clone(),
        EntryType::File => self.inner.file_dbs.clone(),
      };

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

          let (env, content_database, lease_database) = dbs.get()?.get(&fingerprint);
          let put_res = env.begin_rw_txn().and_then(|mut txn| {
            txn.put(content_database, &fingerprint, &bytes, NO_OVERWRITE)?;
            if initial_lease {
              bytestore.lease(
                &lease_database,
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
              "Error storing fingerprint {}: {}",
              fingerprint, err
            )),
          }
        })
        .to_boxed()
    }

    pub fn load_bytes_with<T: Send + 'static, F: Fn(Bytes) -> T + Send + Sync + 'static>(
      &self,
      entry_type: EntryType,
      fingerprint: Fingerprint,
      f: F,
    ) -> BoxFuture<Option<T>, String> {
      if fingerprint == EMPTY_FINGERPRINT {
        // Avoid expensive I/O for this super common case.
        // Also, this allows some client-provided operations (like merging snapshots) to work
        // without needing to first store the empty snapshot.
        return future::ok(Some(f(Bytes::new()))).to_boxed();
      }

      let dbs = match entry_type {
        EntryType::Directory => self.inner.directory_dbs.clone(),
        EntryType::File => self.inner.file_dbs.clone(),
      };

      self
        .inner
        .pool
        .spawn_fn(move || {
          let (env, db, _) = dbs.get()?.get(&fingerprint);
          let ro_txn = env
            .begin_ro_txn()
            .map_err(|err| format!("Failed to begin read transaction: {}", err));
          ro_txn.and_then(|txn| match txn.get(db, &fingerprint) {
            Ok(bytes) => Ok(Some(f(Bytes::from(bytes)))),
            Err(NotFound) => Ok(None),
            Err(err) => Err(format!(
              "Error loading fingerprint {}: {}",
              fingerprint, err,
            )),
          })
        })
        .to_boxed()
    }
  }

  // Each LMDB directory can have at most one concurrent writer.
  // We use this type to shard storage into 16 LMDB directories, based on the first 4 bits of the
  // fingerprint being stored, so that we can write to them in parallel.
  #[derive(Clone)]
  struct ShardedLmdb {
    // First Database is content, second is leases.
    lmdbs: HashMap<u8, (Arc<Environment>, Database, Database)>,
  }

  impl ShardedLmdb {
    pub fn new(root_path: &Path) -> Result<ShardedLmdb, String> {
      debug!("Initializing ShardedLmdb at root {:?}", root_path);
      let mut lmdbs = HashMap::new();

      for b in 0x00..0x10 {
        let key = b << 4;

        let dirname = {
          let mut s = String::new();
          fmt::Write::write_fmt(&mut s, format_args!("{:x}", key)).unwrap();
          s[0..1].to_owned()
        };
        let dir = root_path.join(dirname);
        super::super::safe_create_dir_all(&dir)
          .map_err(|err| format!("Error making directory for store at {:?}: {:?}", dir, err))?;
        debug!("Making ShardedLmdb env for {:?}", dir);
        let env = Environment::new()
            // NO_SYNC
            // =======
            //
            // Don't force fsync on every lmdb write transaction
            //
            // This significantly improves performance on slow or contended disks.
            //
            // On filesystems which preserve order of writes, on system crash this may lead to some
            // transactions being rolled back. This is fine because this is just a write-once
            // content-addressed cache. There is no risk of corruption, just compromised durability.
            //
            // On filesystems which don't preserve the order of writes, this may lead to lmdb
            // corruption on system crash (but in no other circumstances, such as process crash).
            //
            // ------------------------------------------------------------------------------------
            //
            // NO_TLS
            // ======
            //
            // Without this flag, each time a read transaction is started, it eats into our
            // transaction limit (default: 126) until that thread dies.
            //
            // This flag makes transactions be removed from that limit when they are dropped, rather
            // than when their thread dies. This is important, because we perform reads from a
            // thread pool, so our threads never die. Without this flag, all read requests will fail
            // after the first 126.
            //
            // The only down-side is that you need to make sure that any individual OS thread must
            // not try to perform multiple write transactions concurrently. Fortunately, this
            // property holds for us.
            .set_flags(NO_SYNC | NO_TLS)
            // 2 DBs; one for file contents, one for leases.
            .set_max_dbs(2)
            .set_map_size(MAX_LOCAL_STORE_SIZE_BYTES)
            .open(&dir)
            .map_err(|e| format!("Error making env for store at {:?}: {}", dir, e))?;

        debug!("Making ShardedLmdb content database for {:?}", dir);
        let content_database = env
          .create_db(Some("content"), DatabaseFlags::empty())
          .map_err(|e| {
            format!(
              "Error creating/opening content database at {:?}: {}",
              dir, e
            )
          })?;

        debug!("Making ShardedLmdb lease database for {:?}", dir);
        let lease_database = env
          .create_db(Some("leases"), DatabaseFlags::empty())
          .map_err(|e| {
            format!(
              "Error creating/opening content database at {:?}: {}",
              dir, e
            )
          })?;

        lmdbs.insert(key, (Arc::new(env), content_database, lease_database));
      }

      Ok(ShardedLmdb { lmdbs })
    }

    // First Database is content, second is leases.
    pub fn get(&self, fingerprint: &Fingerprint) -> (Arc<Environment>, Database, Database) {
      self.lmdbs[&(fingerprint.0[0] & 0xF0)].clone()
    }

    pub fn all_lmdbs(&self) -> Vec<(Arc<Environment>, Database, Database)> {
      self.lmdbs.values().cloned().collect()
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
    use super::super::super::safe_create_dir_all;
    use super::{ByteStore, EntryType, ResettablePool};
    use bytes::Bytes;
    use futures::Future;
    use hashing::{Digest, Fingerprint};
    use lmdb::{DatabaseFlags, Environment, Transaction, WriteFlags};
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::TempDir;
    use testutil::data::{TestData, TestDirectory};

    #[test]
    fn save_file() {
      let dir = TempDir::new().unwrap();

      let testdata = TestData::roland();
      assert_eq!(
        new_store(dir.path())
          .store_bytes(EntryType::File, testdata.bytes(), false)
          .wait(),
        Ok(testdata.fingerprint())
      );
    }

    #[test]
    fn save_file_is_idempotent() {
      let dir = TempDir::new().unwrap();

      let testdata = TestData::roland();
      new_store(dir.path())
        .store_bytes(EntryType::File, testdata.bytes(), false)
        .wait()
        .unwrap();
      assert_eq!(
        new_store(dir.path())
          .store_bytes(EntryType::File, testdata.bytes(), false)
          .wait(),
        Ok(testdata.fingerprint())
      );
    }

    #[test]
    fn save_file_collision_preserves_first() {
      let dir = TempDir::new().unwrap();

      let bogus_value = Bytes::new();
      let realdata = TestData::roland();

      let sharded_dir = dir
        .path()
        .join("files")
        .join(&realdata.fingerprint().to_hex()[0..1]);
      safe_create_dir_all(&sharded_dir).expect("Making temp dir");

      let env = Environment::new()
        .set_max_dbs(1)
        .open(&sharded_dir)
        .unwrap();
      let database = env.create_db(Some("content"), DatabaseFlags::empty());
      env
        .begin_rw_txn()
        .and_then(|mut txn| {
          txn
            .put(
              database.unwrap(),
              &realdata.fingerprint(),
              &bogus_value,
              WriteFlags::empty(),
            )
            .and_then(|()| txn.commit())
        })
        .unwrap();

      assert_eq!(
        load_file_bytes(&new_store(dir.path()), realdata.fingerprint()),
        Ok(Some(bogus_value.clone()))
      );

      assert_eq!(
        new_store(dir.path())
          .store_bytes(EntryType::File, realdata.bytes(), false)
          .wait(),
        Ok(realdata.fingerprint())
      );

      assert_eq!(
        load_file_bytes(&new_store(dir.path()), realdata.fingerprint()),
        Ok(Some(bogus_value.clone()))
      );
    }

    #[test]
    fn roundtrip_file() {
      let testdata = TestData::roland();
      let dir = TempDir::new().unwrap();

      let store = new_store(dir.path());
      let hash = store
        .store_bytes(EntryType::File, testdata.bytes(), false)
        .wait()
        .unwrap();
      assert_eq!(load_file_bytes(&store, hash), Ok(Some(testdata.bytes())));
    }

    #[test]
    fn missing_file() {
      let dir = TempDir::new().unwrap();
      assert_eq!(
        load_file_bytes(&new_store(dir.path()), TestData::roland().fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn record_and_load_directory_proto() {
      let dir = TempDir::new().unwrap();
      let testdir = TestDirectory::containing_roland();

      assert_eq!(
        &new_store(dir.path())
          .store_bytes(EntryType::Directory, testdir.bytes(), false)
          .wait(),
        &Ok(testdir.fingerprint())
      );

      assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), testdir.fingerprint()),
        Ok(Some(testdir.bytes()))
      );
    }

    #[test]
    fn missing_directory() {
      let dir = TempDir::new().unwrap();
      let testdir = TestDirectory::containing_roland();

      assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), testdir.fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn file_is_not_directory_proto() {
      let dir = TempDir::new().unwrap();
      let testdata = TestData::roland();

      new_store(dir.path())
        .store_bytes(EntryType::File, testdata.bytes(), false)
        .wait()
        .unwrap();

      assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), testdata.fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn garbage_collect_nothing_to_do() {
      let dir = TempDir::new().unwrap();
      let store = new_store(dir.path());
      let bytes = Bytes::from("0123456789");
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
      let dir = TempDir::new().unwrap();
      let store = new_store(dir.path());
      let bytes = Bytes::from("0123456789");
      store
        .store_bytes(EntryType::File, bytes.clone(), false)
        .wait()
        .expect("Error storing");
      let file_fingerprint = Fingerprint::from_hex_string(
        "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
      ).unwrap();
      let file_digest = Digest(file_fingerprint, 10);
      store
        .lease_all(vec![file_digest].iter())
        .expect("Error leasing");
      store.shrink(10).expect("Error shrinking");
      assert_eq!(
        load_bytes(&store, EntryType::File, file_fingerprint),
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
      ).unwrap();
      let bytes_2 = Bytes::from("9876543210");
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
      entries
        .push(load_bytes(&store, EntryType::File, fingerprint_1).expect("Error loading bytes"));
      entries
        .push(load_bytes(&store, EntryType::File, fingerprint_2).expect("Error loading bytes"));
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
      ).unwrap();
      let bytes_2 = Bytes::from("9876543210");
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
      let dir = TempDir::new().unwrap();

      let testdir = TestDirectory::containing_roland();
      let other_testdir = TestDirectory::containing_dnalor();

      let store = new_store(dir.path());
      store
        .store_bytes(EntryType::Directory, testdir.bytes(), false)
        .wait()
        .expect("Error storing");
      store
        .store_bytes(EntryType::Directory, other_testdir.bytes(), false)
        .wait()
        .expect("Error storing");
      store.shrink(80).expect("Error shrinking");
      let mut entries = Vec::new();
      entries.push(
        load_bytes(&store, EntryType::Directory, testdir.fingerprint())
          .expect("Error loading bytes"),
      );
      entries.push(
        load_bytes(&store, EntryType::Directory, other_testdir.fingerprint())
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

      store
        .store_bytes(EntryType::Directory, testdir.bytes(), true)
        .wait()
        .expect("Error storing");

      store
        .store_bytes(EntryType::File, testdata.bytes(), false)
        .wait()
        .expect("Error storing");

      store.shrink(80).expect("Error shrinking");

      assert_eq!(
        load_bytes(&store, EntryType::File, testdata.fingerprint()),
        Ok(None),
        "File was present when it should've been garbage collected"
      );
      assert_eq!(
        load_bytes(&store, EntryType::Directory, testdir.fingerprint()),
        Ok(Some(testdir.bytes())),
        "Directory was missing despite lease"
      );
    }

    #[test]
    fn garbage_collect_remove_file_while_leased_file() {
      let dir = TempDir::new().unwrap();
      let store = new_store(dir.path());

      let testdir = TestDirectory::containing_roland();

      store
        .store_bytes(EntryType::Directory, testdir.bytes(), false)
        .wait()
        .expect("Error storing");
      let fourty_chars = TestData::fourty_chars();
      store
        .store_bytes(EntryType::File, fourty_chars.bytes(), true)
        .wait()
        .expect("Error storing");

      store.shrink(80).expect("Error shrinking");

      assert_eq!(
        load_bytes(&store, EntryType::File, fourty_chars.fingerprint()),
        Ok(Some(fourty_chars.bytes())),
        "File was missing despite lease"
      );
      assert_eq!(
        load_bytes(&store, EntryType::Directory, testdir.fingerprint()),
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

      store
        .store_bytes(EntryType::Directory, testdir.bytes(), true)
        .wait()
        .expect("Error storing");
      store
        .store_bytes(EntryType::File, fourty_chars.bytes(), true)
        .wait()
        .expect("Error storing");

      store
        .store_bytes(EntryType::File, TestData::roland().bytes(), false)
        .wait()
        .expect("Error storing");

      assert_eq!(store.shrink(80), Ok(160));

      assert_eq!(
        load_bytes(&store, EntryType::File, fourty_chars.fingerprint()),
        Ok(Some(fourty_chars.bytes())),
        "Leased file should still be present"
      );
      assert_eq!(
        load_bytes(&store, EntryType::Directory, testdir.fingerprint()),
        Ok(Some(testdir.bytes())),
        "Leased directory should still be present"
      );
      // Whether the unleased file is present is undefined.
    }

    #[test]
    fn entry_type_for_file() {
      let testdata = TestData::roland();
      let testdir = TestDirectory::containing_roland();
      let dir = TempDir::new().unwrap();
      let store = new_store(dir.path());
      store
        .store_bytes(EntryType::Directory, testdir.bytes(), false)
        .wait()
        .expect("Error storing");
      store
        .store_bytes(EntryType::File, testdata.bytes(), false)
        .wait()
        .expect("Error storing");
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
      store
        .store_bytes(EntryType::Directory, testdir.bytes(), false)
        .wait()
        .expect("Error storing");
      store
        .store_bytes(EntryType::File, testdata.bytes(), false)
        .wait()
        .expect("Error storing");
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
      store
        .store_bytes(EntryType::Directory, testdir.bytes(), false)
        .wait()
        .expect("Error storing");
      store
        .store_bytes(EntryType::File, testdata.bytes(), false)
        .wait()
        .expect("Error storing");
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
        store
          .load_bytes_with(EntryType::File, empty_file.fingerprint(), |b| b)
          .wait(),
        Ok(Some(empty_file.bytes())),
      )
    }

    #[test]
    pub fn empty_directory_is_known() {
      let dir = TempDir::new().unwrap();
      let store = new_store(dir.path());
      let empty_dir = TestDirectory::empty();
      assert_eq!(
        store
          .load_bytes_with(EntryType::Directory, empty_dir.fingerprint(), |b| b)
          .wait(),
        Ok(Some(empty_dir.bytes())),
      )
    }

    pub fn new_store<P: AsRef<Path>>(dir: P) -> ByteStore {
      ByteStore::new(dir, Arc::new(ResettablePool::new("test-pool-".to_string()))).unwrap()
    }

    pub fn load_file_bytes(
      store: &ByteStore,
      fingerprint: Fingerprint,
    ) -> Result<Option<Bytes>, String> {
      load_bytes(&store, EntryType::File, fingerprint)
    }

    pub fn load_directory_proto_bytes(
      store: &ByteStore,
      fingerprint: Fingerprint,
    ) -> Result<Option<Bytes>, String> {
      load_bytes(&store, EntryType::Directory, fingerprint)
    }

    fn load_bytes(
      store: &ByteStore,
      entry_type: EntryType,
      fingerprint: Fingerprint,
    ) -> Result<Option<Bytes>, String> {
      store.load_bytes_with(entry_type, fingerprint, |b| b).wait()
    }
  }
}

mod remote {
  use super::EntryType;

  use bazel_protos;
  use boxfuture::{BoxFuture, Boxable};
  use bytes::{Bytes, BytesMut};
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::{self, future, Future, Sink, Stream};
  use grpcio;
  use hashing::{Digest, Fingerprint};
  use resettable::Resettable;
  use sha2::Sha256;
  use std::cmp::min;
  use std::collections::HashSet;
  use std::sync::Arc;
  use std::time::Duration;

  #[derive(Clone)]
  pub struct ByteStore {
    byte_stream_client: Resettable<Arc<bazel_protos::bytestream_grpc::ByteStreamClient>>,
    cas_client:
      Resettable<Arc<bazel_protos::remote_execution_grpc::ContentAddressableStorageClient>>,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
    env: Resettable<Arc<grpcio::Environment>>,
    channel: Resettable<grpcio::Channel>,
  }

  impl ByteStore {
    pub fn new(
      cas_address: String,
      thread_count: usize,
      chunk_size_bytes: usize,
      upload_timeout: Duration,
    ) -> ByteStore {
      let env = Resettable::new(move || Arc::new(grpcio::Environment::new(thread_count)));
      let env2 = env.clone();
      let channel =
        Resettable::new(move || grpcio::ChannelBuilder::new(env2.get()).connect(&cas_address));
      let channel2 = channel.clone();
      let channel3 = channel.clone();
      let byte_stream_client = Resettable::new(move || {
        Arc::new(bazel_protos::bytestream_grpc::ByteStreamClient::new(
          channel2.get(),
        ))
      });
      let cas_client = Resettable::new(move || {
        Arc::new(
          bazel_protos::remote_execution_grpc::ContentAddressableStorageClient::new(channel3.get()),
        )
      });
      ByteStore {
        byte_stream_client,
        cas_client,
        chunk_size_bytes,
        upload_timeout,
        env,
        channel,
      }
    }

    pub fn reset_threadpool(&self) {
      self.channel.reset();
      self.env.reset();
      self.cas_client.reset();
      self.byte_stream_client.reset();
    }

    pub fn store_bytes(&self, bytes: Bytes) -> BoxFuture<Digest, String> {
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
      match self
        .byte_stream_client
        .get()
        .write_opt(grpcio::CallOption::default().timeout(self.upload_timeout))
      {
        Err(err) => future::err(format!(
          "Error attempting to connect to upload fingerprint {}: {:?}",
          fingerprint, err
        )).to_boxed(),
        Ok((sender, receiver)) => {
          let chunk_size_bytes = self.chunk_size_bytes;
          let stream =
            futures::stream::unfold::<_, _, futures::future::FutureResult<_, grpcio::Error>, _>(
              (0, false),
              move |(offset, has_sent_any)| {
                if offset >= bytes.len() && has_sent_any {
                  None
                } else {
                  let mut req = bazel_protos::bytestream::WriteRequest::new();
                  req.set_resource_name(resource_name.clone());
                  req.set_write_offset(offset as i64);
                  let next_offset = min(offset + chunk_size_bytes, bytes.len());
                  req.set_finish_write(next_offset == bytes.len());
                  req.set_data(bytes.slice(offset, next_offset));
                  Some(future::ok((
                    (req, grpcio::WriteFlags::default()),
                    (next_offset, true),
                  )))
                }
              },
            );

          future::ok(self.byte_stream_client.get())
            .join(sender.send_all(stream).map_err(move |e| {
              format!(
                "Error attempting to upload fingerprint {}: {:?}",
                fingerprint, e
              )
            }))
            .and_then(move |_| {
              receiver.map_err(move |e| {
                format!(
                  "Error from server when uploading fingerprint {}: {:?}",
                  fingerprint, e
                )
              })
            })
            .and_then(move |received| {
              if received.get_committed_size() != len as i64 {
                Err(format!(
                  "Uploading file with fingerprint {}: want commited size {} but got {}",
                  fingerprint,
                  len,
                  received.get_committed_size()
                ))
              } else {
                Ok(Digest(fingerprint, len))
              }
            })
            .to_boxed()
        }
      }
    }

    pub fn load_bytes_with<T: Send + 'static, F: Fn(Bytes) -> T + Send + Sync + 'static>(
      &self,
      _entry_type: EntryType,
      digest: Digest,
      f: F,
    ) -> BoxFuture<Option<T>, String> {
      match self.byte_stream_client.get().read(&{
        let mut req = bazel_protos::bytestream::ReadRequest::new();
        req.set_resource_name(format!("/blobs/{}/{}", digest.0, digest.1));
        req.set_read_offset(0);
        // 0 means no limit.
        req.set_read_limit(0);
        req
      }) {
        Ok(stream) => {
          // We shouldn't have to pass around the client here, it's a workaround for
          // https://github.com/pingcap/grpc-rs/issues/123
          future::ok(self.byte_stream_client.get())
            .join(
              stream.fold(BytesMut::with_capacity(digest.1), move |mut bytes, r| {
                bytes.extend_from_slice(&r.data);
                future::ok::<_, grpcio::Error>(bytes)
              }),
            )
            .map(|(_client, bytes)| Some(bytes.freeze()))
            .or_else(|e| match e {
              grpcio::Error::RpcFailure(grpcio::RpcStatus {
                status: grpcio::RpcStatusCode::NotFound,
                ..
              }) => Ok(None),
              _ => Err(format!(
                "Error from server in response to CAS read request: {:?}",
                e
              )),
            })
            .map(move |maybe_bytes| maybe_bytes.map(f))
            .to_boxed()
        }
        Err(err) => future::err(format!(
          "Error making CAS read request for {:?}: {:?}",
          digest, err
        )).to_boxed(),
      }
    }

    pub fn list_missing_digests<'a, Digests: Iterator<Item = &'a Digest>>(
      &self,
      digests: Digests,
    ) -> Result<HashSet<Digest>, String> {
      let mut request = bazel_protos::remote_execution::FindMissingBlobsRequest::new();
      for digest in digests {
        request.mut_blob_digests().push(digest.into());
      }
      self
        .cas_client
        .get()
        .find_missing_blobs(&request)
        .map_err(|err| {
          format!(
            "Error from server in response to find_missing_blobs_request: {:?}",
            err
          )
        })
        .and_then(|response| {
          response
            .get_missing_blob_digests()
            .iter()
            .map(|digest| digest.into())
            .collect()
        })
    }
  }

  #[cfg(test)]
  mod tests {
    use super::super::EntryType;
    use super::ByteStore;
    use bytes::Bytes;
    use futures::Future;
    use hashing::Digest;
    use mock::StubCAS;
    use std::collections::HashSet;
    use std::time::Duration;
    use testutil::data::{TestData, TestDirectory};

    use super::super::tests::{big_file_bytes, big_file_digest, big_file_fingerprint, new_cas};

    #[test]
    fn loads_file() {
      let testdata = TestData::roland();
      let cas = new_cas(10);

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), testdata.digest()).unwrap(),
        Some(testdata.bytes())
      );
    }

    #[test]
    fn missing_file() {
      let cas = StubCAS::empty();

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), TestData::roland().digest()),
        Ok(None)
      );
    }

    #[test]
    fn load_directory() {
      let cas = new_cas(10);
      let testdir = TestDirectory::containing_roland();

      assert_eq!(
        load_directory_proto_bytes(&new_byte_store(&cas), testdir.digest()),
        Ok(Some(testdir.bytes()))
      );
    }

    #[test]
    fn missing_directory() {
      let cas = StubCAS::empty();

      assert_eq!(
        load_directory_proto_bytes(
          &new_byte_store(&cas),
          TestDirectory::containing_roland().digest()
        ),
        Ok(None)
      );
    }

    #[test]
    fn load_file_grpc_error() {
      let cas = StubCAS::always_errors();

      let error = load_file_bytes(&new_byte_store(&cas), TestData::roland().digest())
        .expect_err("Want error");
      assert!(
        error.contains("StubCAS is configured to always fail"),
        format!("Bad error message, got: {}", error)
      )
    }

    #[test]
    fn load_directory_grpc_error() {
      let cas = StubCAS::always_errors();

      let error = load_directory_proto_bytes(
        &new_byte_store(&cas),
        TestDirectory::containing_roland().digest(),
      ).expect_err("Want error");
      assert!(
        error.contains("StubCAS is configured to always fail"),
        format!("Bad error message, got: {}", error)
      )
    }

    #[test]
    fn fetch_less_than_one_chunk() {
      let testdata = TestData::roland();
      let cas = new_cas(testdata.bytes().len() + 1);

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), testdata.digest()),
        Ok(Some(testdata.bytes()))
      )
    }

    #[test]
    fn fetch_exactly_one_chunk() {
      let testdata = TestData::roland();
      let cas = new_cas(testdata.bytes().len());

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), testdata.digest()),
        Ok(Some(testdata.bytes()))
      )
    }

    #[test]
    fn fetch_multiple_chunks_exact() {
      let testdata = TestData::roland();
      let cas = new_cas(1);

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), testdata.digest()),
        Ok(Some(testdata.bytes()))
      )
    }

    #[test]
    fn fetch_multiple_chunks_nonfactor() {
      let testdata = TestData::roland();
      let cas = new_cas(9);

      assert_eq!(
        load_file_bytes(&new_byte_store(&cas), testdata.digest()),
        Ok(Some(testdata.bytes()))
      )
    }

    #[test]
    fn write_file_one_chunk() {
      let testdata = TestData::roland();
      let cas = StubCAS::empty();

      let store = new_byte_store(&cas);
      assert_eq!(
        store.store_bytes(testdata.bytes()).wait(),
        Ok(testdata.digest())
      );

      let blobs = cas.blobs.lock().unwrap();
      assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));
    }

    #[test]
    fn write_file_multiple_chunks() {
      let cas = StubCAS::empty();

      let store = ByteStore::new(cas.address(), 1, 10 * 1024, Duration::from_secs(5));

      let all_the_henries = big_file_bytes();

      let fingerprint = big_file_fingerprint();

      assert_eq!(
        store.store_bytes(all_the_henries.clone()).wait(),
        Ok(big_file_digest())
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
    fn write_empty_file() {
      let empty_file = TestData::empty();
      let cas = StubCAS::empty();

      let store = new_byte_store(&cas);
      assert_eq!(
        store.store_bytes(empty_file.bytes()).wait(),
        Ok(empty_file.digest())
      );

      let blobs = cas.blobs.lock().unwrap();
      assert_eq!(
        blobs.get(&empty_file.fingerprint()),
        Some(&empty_file.bytes())
      );
    }

    #[test]
    fn write_file_errors() {
      let cas = StubCAS::always_errors();

      let store = new_byte_store(&cas);
      let error = store
        .store_bytes(TestData::roland().bytes())
        .wait()
        .expect_err("Want error");
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
        "doesnotexist.example".to_owned(),
        1,
        10 * 1024 * 1024,
        Duration::from_secs(1),
      );
      let error = store
        .store_bytes(TestData::roland().bytes())
        .wait()
        .expect_err("Want error");
      assert!(
        error.contains("Error attempting to upload fingerprint"),
        format!("Bad error message, got: {}", error)
      );
    }

    #[test]
    fn list_missing_digests_none_missing() {
      let cas = new_cas(1024);

      let store = new_byte_store(&cas);
      assert_eq!(
        store.list_missing_digests(vec![TestData::roland().digest()].iter()),
        Ok(HashSet::new())
      );
    }

    #[test]
    fn list_missing_digests_some_missing() {
      let cas = StubCAS::empty();

      let store = new_byte_store(&cas);

      let digest = TestData::roland().digest();

      let mut digest_set = HashSet::new();
      digest_set.insert(digest);

      assert_eq!(
        store.list_missing_digests(vec![digest].iter()),
        Ok(digest_set)
      );
    }

    #[test]
    fn list_missing_digests_error() {
      let cas = StubCAS::always_errors();

      let store = new_byte_store(&cas);

      let error = store
        .list_missing_digests(vec![TestData::roland().digest()].iter())
        .expect_err("Want error");
      assert!(
        error.contains("StubCAS is configured to always fail"),
        format!("Bad error message, got: {}", error)
      );
    }

    fn new_byte_store(cas: &StubCAS) -> ByteStore {
      ByteStore::new(cas.address(), 1, 10 * 1024 * 1024, Duration::from_secs(1))
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
      store.load_bytes_with(entry_type, digest, |b| b).wait()
    }
  }
}

#[cfg(test)]
mod tests {
  use super::{local, EntryType, FileContent, Store};

  use bazel_protos;
  use bytes::Bytes;
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::Future;
  use hashing::{Digest, Fingerprint};
  use mock::StubCAS;
  use pool::ResettablePool;
  use protobuf::Message;
  use sha2::Sha256;
  use std;
  use std::collections::HashMap;
  use std::fs::File;
  use std::io::Read;
  use std::os::unix::fs::PermissionsExt;
  use std::path::{Path, PathBuf};
  use std::sync::Arc;
  use std::time::Duration;
  use tempfile::TempDir;
  use testutil::data::{TestData, TestDirectory};

  pub fn big_file_fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string("8dfba0adc29389c63062a68d76b2309b9a2486f1ab610c4720beabbdc273301f")
      .unwrap()
  }

  pub fn big_file_digest() -> Digest {
    Digest(big_file_fingerprint(), big_file_bytes().len())
  }

  pub fn big_file_bytes() -> Bytes {
    let mut f = File::open(
      PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("testdata")
        .join("all_the_henries"),
    ).expect("Error opening all_the_henries");
    let mut bytes = Vec::new();
    f.read_to_end(&mut bytes)
      .expect("Error reading all_the_henries");
    Bytes::from(bytes)
  }

  pub fn extra_big_file_fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string("8ae6924fa104396614b99ce1f6aa3b4d85273ef158191b3784c6dbbdb47055cd")
      .unwrap()
  }

  pub fn extra_big_file_digest() -> Digest {
    Digest(extra_big_file_fingerprint(), extra_big_file_bytes().len())
  }

  pub fn extra_big_file_bytes() -> Bytes {
    let mut bytes = big_file_bytes();
    bytes.extend(&big_file_bytes());
    bytes
  }

  pub fn load_file_bytes(store: &Store, digest: Digest) -> Result<Option<Bytes>, String> {
    store.load_file_bytes_with(digest, |bytes| bytes).wait()
  }

  pub fn new_cas(chunk_size_bytes: usize) -> StubCAS {
    StubCAS::with_content(
      chunk_size_bytes as i64,
      vec![TestData::roland()],
      vec![TestDirectory::containing_roland()],
    )
  }

  fn new_local_store<P: AsRef<Path>>(dir: P) -> Store {
    Store::local_only(dir, Arc::new(ResettablePool::new("test-pool-".to_string())))
      .expect("Error creating local store")
  }

  fn new_store<P: AsRef<Path>>(dir: P, cas_address: String) -> Store {
    Store::with_remote(
      dir,
      Arc::new(ResettablePool::new("test-pool-".to_string())),
      cas_address,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
    ).unwrap()
  }

  #[test]
  fn load_file_prefers_local() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    local::tests::new_store(dir.path())
      .store_bytes(EntryType::File, testdata.bytes(), false)
      .wait()
      .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
      load_file_bytes(&new_store(dir.path(), cas.address()), testdata.digest()),
      Ok(Some(testdata.bytes()))
    );
    assert_eq!(0, cas.read_request_count());
  }

  #[test]
  fn load_directory_prefers_local() {
    let dir = TempDir::new().unwrap();

    let testdir = TestDirectory::containing_roland();

    local::tests::new_store(dir.path())
      .store_bytes(EntryType::Directory, testdir.bytes(), false)
      .wait()
      .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_directory(testdir.digest())
        .wait(),
      Ok(Some(testdir.directory()))
    );
    assert_eq!(0, cas.read_request_count());
  }

  #[test]
  fn load_file_falls_back_and_backfills() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let cas = new_cas(1024);
    assert_eq!(
      load_file_bytes(&new_store(dir.path(), cas.address()), testdata.digest()),
      Ok(Some(testdata.bytes())),
      "Read from CAS"
    );
    assert_eq!(1, cas.read_request_count());
    assert_eq!(
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), testdata.fingerprint()),
      Ok(Some(testdata.bytes())),
      "Read from local cache"
    );
  }

  #[test]
  fn load_directory_falls_back_and_backfills() {
    let dir = TempDir::new().unwrap();

    let cas = new_cas(1024);

    let testdir = TestDirectory::containing_roland();

    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_directory(testdir.digest())
        .wait(),
      Ok(Some(testdir.directory()))
    );
    assert_eq!(1, cas.read_request_count());
    assert_eq!(
      local::tests::load_directory_proto_bytes(
        &local::tests::new_store(dir.path()),
        testdir.fingerprint(),
      ),
      Ok(Some(testdir.bytes()))
    );
  }

  #[test]
  fn load_file_missing_is_none() {
    let dir = TempDir::new().unwrap();

    let cas = StubCAS::empty();
    assert_eq!(
      load_file_bytes(
        &new_store(dir.path(), cas.address()),
        TestData::roland().digest()
      ),
      Ok(None)
    );
    assert_eq!(1, cas.read_request_count());
  }

  #[test]
  fn load_directory_missing_is_none() {
    let dir = TempDir::new().unwrap();

    let cas = StubCAS::empty();
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_directory(TestDirectory::containing_roland().digest())
        .wait(),
      Ok(None)
    );
    assert_eq!(1, cas.read_request_count());
  }

  #[test]
  fn load_file_remote_error_is_error() {
    let dir = TempDir::new().unwrap();

    let cas = StubCAS::always_errors();
    let error = load_file_bytes(
      &new_store(dir.path(), cas.address()),
      TestData::roland().digest(),
    ).expect_err("Want error");
    assert_eq!(1, cas.read_request_count());
    assert!(
      error.contains("StubCAS is configured to always fail"),
      "Bad error message"
    );
  }

  #[test]
  fn load_directory_remote_error_is_error() {
    let dir = TempDir::new().unwrap();

    let cas = StubCAS::always_errors();
    let error = new_store(dir.path(), cas.address())
      .load_directory(TestData::roland().digest())
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
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let cas = new_cas(1024);
    new_store(dir.path(), cas.address())
      .load_directory(testdata.digest())
      .wait()
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_directory_proto_bytes(
        &local::tests::new_store(dir.path()),
        testdata.fingerprint()
      ),
      Ok(None)
    );
  }

  #[test]
  fn non_canonical_remote_directory_is_error() {
    let mut non_canonical_directory = TestDirectory::containing_roland().directory();
    non_canonical_directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("roland".to_string());
      file.set_digest((&TestData::roland().digest()).into());
      file
    });
    let non_canonical_directory_bytes = Bytes::from(
      non_canonical_directory
        .write_to_bytes()
        .expect("Error serializing proto"),
    );
    let non_canonical_directory_fingerprint = {
      let mut hasher = Sha256::default();
      hasher.input(&non_canonical_directory_bytes);
      Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
    };
    let directory_digest = Digest(
      non_canonical_directory_fingerprint,
      non_canonical_directory_bytes.len(),
    );

    let dir = TempDir::new().unwrap();

    let cas = StubCAS::with_unverified_content(
      1024,
      vec![(
        non_canonical_directory_fingerprint.clone(),
        non_canonical_directory_bytes,
      )].into_iter()
        .collect(),
    );
    new_store(dir.path(), cas.address())
      .load_directory(directory_digest.clone())
      .wait()
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_directory_proto_bytes(
        &local::tests::new_store(dir.path()),
        non_canonical_directory_fingerprint,
      ),
      Ok(None)
    );
  }

  #[test]
  fn wrong_remote_file_bytes_is_error() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let cas = StubCAS::with_unverified_content(
      1024,
      vec![(
        testdata.fingerprint(),
        TestDirectory::containing_roland().bytes(),
      )].into_iter()
        .collect(),
    );
    load_file_bytes(&new_store(dir.path(), cas.address()), testdata.digest())
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), testdata.fingerprint()),
      Ok(None)
    );
  }

  #[test]
  fn wrong_remote_directory_bytes_is_error() {
    let dir = TempDir::new().unwrap();

    let testdir = TestDirectory::containing_dnalor();

    let cas = StubCAS::with_unverified_content(
      1024,
      vec![(
        testdir.fingerprint(),
        TestDirectory::containing_roland().bytes(),
      )].into_iter()
        .collect(),
    );
    load_file_bytes(&new_store(dir.path(), cas.address()), testdir.digest())
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), testdir.fingerprint()),
      Ok(None)
    );
  }

  #[test]
  fn expand_empty_directory() {
    let dir = TempDir::new().unwrap();

    let empty_dir = TestDirectory::empty();

    let expanded = new_local_store(dir.path())
      .expand_directory(empty_dir.digest())
      .wait()
      .expect("Error expanding directory");
    let want: HashMap<Digest, EntryType> = vec![(empty_dir.digest(), EntryType::Directory)]
      .into_iter()
      .collect();
    assert_eq!(expanded, want);
  }

  #[test]
  fn expand_flat_directory() {
    let dir = TempDir::new().unwrap();

    let roland = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
      .record_directory(&testdir.directory(), false)
      .wait()
      .expect("Error storing directory locally");

    let expanded = new_local_store(dir.path())
      .expand_directory(testdir.digest())
      .wait()
      .expect("Error expanding directory");
    let want: HashMap<Digest, EntryType> = vec![
      (testdir.digest(), EntryType::Directory),
      (roland.digest(), EntryType::File),
    ].into_iter()
      .collect();
    assert_eq!(expanded, want);
  }

  #[test]
  fn expand_recursive_directory() {
    let dir = TempDir::new().unwrap();

    let roland = TestData::roland();
    let catnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland();
    let recursive_testdir = TestDirectory::recursive();

    new_local_store(dir.path())
      .record_directory(&recursive_testdir.directory(), false)
      .wait()
      .expect("Error storing directory locally");
    new_local_store(dir.path())
      .record_directory(&testdir.directory(), false)
      .wait()
      .expect("Error storing directory locally");

    let expanded = new_local_store(dir.path())
      .expand_directory(recursive_testdir.digest())
      .wait()
      .expect("Error expanding directory");
    let want: HashMap<Digest, EntryType> = vec![
      (recursive_testdir.digest(), EntryType::Directory),
      (testdir.digest(), EntryType::Directory),
      (roland.digest(), EntryType::File),
      (catnip.digest(), EntryType::File),
    ].into_iter()
      .collect();
    assert_eq!(expanded, want);
  }

  #[test]
  fn expand_missing_directory() {
    let dir = TempDir::new().unwrap();
    let digest = TestDirectory::containing_roland().digest();
    let error = new_local_store(dir.path())
      .expand_directory(digest)
      .wait()
      .expect_err("Want error");
    assert!(
      error.contains(&format!("{:?}", digest)),
      "Bad error message: {}",
      error
    );
  }

  #[test]
  fn expand_directory_missing_subdir() {
    let dir = TempDir::new().unwrap();

    let recursive_testdir = TestDirectory::recursive();

    new_local_store(dir.path())
      .record_directory(&recursive_testdir.directory(), false)
      .wait()
      .expect("Error storing directory locally");

    let error = new_local_store(dir.path())
      .expand_directory(recursive_testdir.digest())
      .wait()
      .expect_err("Want error");
    assert!(
      error.contains(&format!(
        "{}",
        TestDirectory::containing_roland().fingerprint()
      )),
      "Bad error message: {}",
      error
    );
  }

  #[test]
  fn uploads_files() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testdata = TestData::roland();

    new_local_store(dir.path())
      .store_file_bytes(testdata.bytes(), false)
      .wait()
      .expect("Error storing file locally");

    assert_eq!(cas.blobs.lock().unwrap().get(&testdata.fingerprint()), None);

    new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![testdata.digest()])
      .wait()
      .expect("Error uploading file");

    assert_eq!(
      cas.blobs.lock().unwrap().get(&testdata.fingerprint()),
      Some(&testdata.bytes())
    );
  }

  #[test]
  fn uploads_directories_recursively() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
      .record_directory(&testdir.directory(), false)
      .wait()
      .expect("Error storing directory locally");
    new_local_store(dir.path())
      .store_file_bytes(testdata.bytes(), false)
      .wait()
      .expect("Error storing file locally");

    assert_eq!(cas.blobs.lock().unwrap().get(&testdata.fingerprint()), None);
    assert_eq!(cas.blobs.lock().unwrap().get(&testdir.fingerprint()), None);

    new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![testdir.digest()])
      .wait()
      .expect("Error uploading directory");

    assert_eq!(
      cas.blobs.lock().unwrap().get(&testdir.fingerprint()),
      Some(&testdir.bytes())
    );
    assert_eq!(
      cas.blobs.lock().unwrap().get(&testdata.fingerprint()),
      Some(&testdata.bytes())
    );
  }

  #[test]
  fn uploads_files_recursively_when_under_three_digests_ignoring_items_already_in_cas() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
      .record_directory(&testdir.directory(), false)
      .wait()
      .expect("Error storing directory locally");
    new_local_store(dir.path())
      .store_file_bytes(testdata.bytes(), false)
      .wait()
      .expect("Error storing file locally");

    new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![testdata.digest()])
      .wait()
      .expect("Error uploading file");

    assert_eq!(cas.write_message_sizes.lock().unwrap().len(), 1);
    assert_eq!(
      cas.blobs.lock().unwrap().get(&testdata.fingerprint()),
      Some(&testdata.bytes())
    );
    assert_eq!(cas.blobs.lock().unwrap().get(&testdir.fingerprint()), None);

    new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![testdir.digest()])
      .wait()
      .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().unwrap().len(), 3);
    assert_eq!(
      cas.blobs.lock().unwrap().get(&testdir.fingerprint()),
      Some(&testdir.bytes())
    );
  }

  #[test]
  fn does_not_reupload_file_already_in_cas_when_requested_with_three_other_digests() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let catnip = TestData::catnip();
    let roland = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
      .record_directory(&testdir.directory(), false)
      .wait()
      .expect("Error storing directory locally");
    new_local_store(dir.path())
      .store_file_bytes(roland.bytes(), false)
      .wait()
      .expect("Error storing file locally");
    new_local_store(dir.path())
      .store_file_bytes(catnip.bytes(), false)
      .wait()
      .expect("Error storing file locally");

    new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![roland.digest()])
      .wait()
      .expect("Error uploading big file");

    assert_eq!(cas.write_message_sizes.lock().unwrap().len(), 1);
    assert_eq!(
      cas.blobs.lock().unwrap().get(&roland.fingerprint()),
      Some(&roland.bytes())
    );
    assert_eq!(cas.blobs.lock().unwrap().get(&catnip.fingerprint()), None);
    assert_eq!(cas.blobs.lock().unwrap().get(&testdir.fingerprint()), None);

    new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![testdir.digest(), catnip.digest()])
      .wait()
      .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().unwrap().len(), 3);
    assert_eq!(
      cas.blobs.lock().unwrap().get(&catnip.fingerprint()),
      Some(&catnip.bytes())
    );
    assert_eq!(
      cas.blobs.lock().unwrap().get(&testdir.fingerprint()),
      Some(&testdir.bytes())
    );
  }

  #[test]
  fn does_not_reupload_big_file_already_in_cas() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    new_local_store(dir.path())
      .store_file_bytes(extra_big_file_bytes(), false)
      .wait()
      .expect("Error storing file locally");

    new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![extra_big_file_digest()])
      .wait()
      .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().unwrap().len(), 1);
    assert_eq!(
      cas.blobs.lock().unwrap().get(&extra_big_file_fingerprint()),
      Some(&extra_big_file_bytes())
    );

    new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![extra_big_file_digest()])
      .wait()
      .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().unwrap().len(), 1);
    assert_eq!(
      cas.blobs.lock().unwrap().get(&extra_big_file_fingerprint()),
      Some(&extra_big_file_bytes())
    );
  }

  #[test]
  fn upload_missing_files() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testdata = TestData::roland();

    assert_eq!(cas.blobs.lock().unwrap().get(&testdata.fingerprint()), None);

    let error = new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![testdata.digest()])
      .wait()
      .expect_err("Want error");
    assert_eq!(
      error,
      format!("Failed to upload digest {:?}: Not found", testdata.digest())
    );
  }

  #[test]
  fn upload_missing_file_in_directory() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
      .record_directory(&testdir.directory(), false)
      .wait()
      .expect("Error storing directory locally");

    assert_eq!(cas.blobs.lock().unwrap().get(&testdir.fingerprint()), None);
    assert_eq!(cas.blobs.lock().unwrap().get(&testdir.fingerprint()), None);

    let error = new_store(dir.path(), cas.address())
      .ensure_remote_has_recursive(vec![testdir.digest()])
      .wait()
      .expect_err("Want error");
    assert_eq!(
      error,
      format!(
        "Failed to upload digest {:?}: Not found",
        TestData::roland().digest()
      ),
      "Bad error message"
    );
  }

  #[test]
  fn materialize_missing_file() {
    let materialize_dir = TempDir::new().unwrap();
    let file = materialize_dir.path().join("file");

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
      .materialize_file(file.clone(), TestData::roland().digest(), false)
      .wait()
      .expect_err("Want unknown digest error");
  }

  #[test]
  fn materialize_file() {
    let materialize_dir = TempDir::new().unwrap();
    let file = materialize_dir.path().join("file");

    let testdata = TestData::roland();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
      .store_file_bytes(testdata.bytes(), false)
      .wait()
      .expect("Error saving bytes");
    store
      .materialize_file(file.clone(), testdata.digest(), false)
      .wait()
      .expect("Error materializing file");
    assert_eq!(file_contents(&file), testdata.bytes());
    assert!(!is_executable(&file));
  }

  #[test]
  fn materialize_file_executable() {
    let materialize_dir = TempDir::new().unwrap();
    let file = materialize_dir.path().join("file");

    let testdata = TestData::roland();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
      .store_file_bytes(testdata.bytes(), false)
      .wait()
      .expect("Error saving bytes");
    store
      .materialize_file(file.clone(), testdata.digest(), true)
      .wait()
      .expect("Error materializing file");
    assert_eq!(file_contents(&file), testdata.bytes());
    assert!(is_executable(&file));
  }

  #[test]
  fn materialize_missing_directory() {
    let materialize_dir = TempDir::new().unwrap();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
      .materialize_directory(
        materialize_dir.path().to_owned(),
        TestDirectory::recursive().digest(),
      )
      .wait()
      .expect_err("Want unknown digest error");
  }

  #[test]
  fn materialize_directory() {
    let materialize_dir = TempDir::new().unwrap();

    let roland = TestData::roland();
    let catnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland();
    let recursive_testdir = TestDirectory::recursive();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
      .record_directory(&recursive_testdir.directory(), false)
      .wait()
      .expect("Error saving recursive Directory");
    store
      .record_directory(&testdir.directory(), false)
      .wait()
      .expect("Error saving Directory");
    store
      .store_file_bytes(roland.bytes(), false)
      .wait()
      .expect("Error saving file bytes");
    store
      .store_file_bytes(catnip.bytes(), false)
      .wait()
      .expect("Error saving catnip file bytes");

    store
      .materialize_directory(
        materialize_dir.path().to_owned(),
        recursive_testdir.digest(),
      )
      .wait()
      .expect("Error materializing");

    assert_eq!(list_dir(materialize_dir.path()), vec!["cats", "treats"]);
    assert_eq!(
      file_contents(&materialize_dir.path().join("treats")),
      catnip.bytes()
    );
    assert_eq!(
      list_dir(&materialize_dir.path().join("cats")),
      vec!["roland"]
    );
    assert_eq!(
      file_contents(&materialize_dir.path().join("cats").join("roland")),
      roland.bytes()
    );
  }

  #[test]
  fn materialize_directory_executable() {
    let materialize_dir = TempDir::new().unwrap();

    let catnip = TestData::catnip();
    let testdir = TestDirectory::with_mixed_executable_files();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
      .record_directory(&testdir.directory(), false)
      .wait()
      .expect("Error saving Directory");
    store
      .store_file_bytes(catnip.bytes(), false)
      .wait()
      .expect("Error saving catnip file bytes");

    store
      .materialize_directory(materialize_dir.path().to_owned(), testdir.digest())
      .wait()
      .expect("Error materializing");

    assert_eq!(list_dir(materialize_dir.path()), vec!["feed", "food"]);
    assert_eq!(
      file_contents(&materialize_dir.path().join("feed")),
      catnip.bytes()
    );
    assert_eq!(
      file_contents(&materialize_dir.path().join("food")),
      catnip.bytes()
    );
    assert!(is_executable(&materialize_dir.path().join("feed")));
    assert!(!is_executable(&materialize_dir.path().join("food")));
  }

  #[test]
  fn works_after_reset_prefork() {
    let dir = TempDir::new().unwrap();
    let cas = new_cas(1024);

    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    let store = new_store(dir.path(), cas.address());

    // Fetches from remote, so initialises both the local and remote ByteStores:
    assert_eq!(
      store.load_file_bytes_with(testdata.digest(), |b| b).wait(),
      Ok(Some(testdata.bytes()))
    );

    store.reset_prefork();

    // Already exists in local store:
    assert_eq!(
      store.load_file_bytes_with(testdata.digest(), |b| b).wait(),
      Ok(Some(testdata.bytes()))
    );

    // Requires an RPC:
    assert_eq!(
      store.load_directory(testdir.digest()).wait(),
      Ok(Some(testdir.directory()))
    );
  }

  #[test]
  fn contents_for_directory_empty() {
    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());

    let file_contents = store
      .contents_for_directory(&TestDirectory::empty().directory())
      .wait()
      .expect("Getting FileContents");

    assert_same_filecontents(file_contents, vec![]);
  }

  #[test]
  fn contents_for_directory() {
    let roland = TestData::roland();
    let catnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland();
    let recursive_testdir = TestDirectory::recursive();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
      .record_directory(&recursive_testdir.directory(), false)
      .wait()
      .expect("Error saving recursive Directory");
    store
      .record_directory(&testdir.directory(), false)
      .wait()
      .expect("Error saving Directory");
    store
      .store_file_bytes(roland.bytes(), false)
      .wait()
      .expect("Error saving file bytes");
    store
      .store_file_bytes(catnip.bytes(), false)
      .wait()
      .expect("Error saving catnip file bytes");

    let file_contents = store
      .contents_for_directory(&recursive_testdir.directory())
      .wait()
      .expect("Getting FileContents");

    assert_same_filecontents(
      file_contents,
      vec![
        FileContent {
          path: PathBuf::from("cats").join("roland"),
          content: roland.bytes(),
        },
        FileContent {
          path: PathBuf::from("treats"),
          content: catnip.bytes(),
        },
      ],
    );
  }

  fn assert_same_filecontents(left: Vec<FileContent>, right: Vec<FileContent>) {
    assert_eq!(
      left.len(),
      right.len(),
      "FileContents did not match, different lengths: left: {:?} right: {:?}",
      left,
      right
    );

    let mut success = true;
    for (index, (l, r)) in left.iter().zip(right.iter()).enumerate() {
      if l.path != r.path {
        success = false;
        eprintln!(
          "Paths did not match for index {}: {:?}, {:?}",
          index, l.path, r.path
        );
      }
      if l.content != r.content {
        success = false;
        eprintln!(
          "Content did not match for index {}: {:?}, {:?}",
          index, l.content, r.content
        );
      }
    }
    assert!(
      success,
      "FileContents did not match: Left: {:?}, Right: {:?}",
      left, right
    );
  }

  fn list_dir(path: &Path) -> Vec<String> {
    let mut v: Vec<_> = std::fs::read_dir(path)
      .expect("Listing dir")
      .map(|entry| {
        entry
          .expect("Error reading entry")
          .file_name()
          .to_string_lossy()
          .to_string()
      })
      .collect();
    v.sort();
    v
  }

  fn file_contents(path: &Path) -> Bytes {
    let mut contents = Vec::new();
    std::fs::File::open(path)
      .and_then(|mut f| f.read_to_end(&mut contents))
      .expect("Error reading file");
    Bytes::from(contents)
  }

  fn is_executable(path: &Path) -> bool {
    std::fs::metadata(path)
      .expect("Getting metadata")
      .permissions()
      .mode() & 0o100 == 0o100
  }
}
