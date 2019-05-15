use crate::{BackoffConfig, FileContent};

use bazel_protos;
use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use dirs;
use futures::{future, Future};
use hashing::Digest;
use protobuf::Message;
use serde_derive::Serialize;
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use parking_lot::Mutex;

// This is the maximum size any particular local LMDB store file is allowed to grow to.
// It doesn't reflect space allocated on disk, or RAM allocated (it may be reflected in VIRT but
// not RSS). There is no practical upper bound on this number, so we set it ridiculously high.
const MAX_LOCAL_STORE_SIZE_BYTES: usize = 1024 * 1024 * 1024 * 1024 / 10;

// This is the target number of bytes which should be present in all combined LMDB store files
// after garbage collection. We almost certainly want to make this configurable.
pub const DEFAULT_LOCAL_STORE_GC_TARGET_BYTES: usize = 4 * 1024 * 1024 * 1024;

// Summary of the files and directories uploaded with an operation
// ingested_file_{count, bytes}: Number and combined size of processed files
// uploaded_file_{count, bytes}: Number and combined size of files uploaded to the remote
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize)]
pub struct UploadSummary {
  pub ingested_file_count: usize,
  pub ingested_file_bytes: usize,
  pub uploaded_file_count: usize,
  pub uploaded_file_bytes: usize,
  #[serde(skip)]
  pub upload_wall_time: Duration,
}

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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ShrinkBehavior {
  ///
  /// Free up space in the store for future writes (marking pages as dirty), but don't proactively
  /// free up the disk space that was used. This is fast and safe, but won't free up disk space.
  ///
  Fast,

  ///
  /// As with Fast, but also free up disk space from no-longer-used data. This may use extra disk
  /// space temporarily while compaction is happening.
  ///
  /// Note that any processes which have the Store open may need to re-open the Store after this
  /// operation, as the underlying files may have been re-written.
  ///
  Compact,
}

// Note that Store doesn't implement ByteStore because it operates at a higher level of abstraction,
// considering Directories as a standalone concept, rather than a buffer of bytes.
// This has the nice property that Directories can be trusted to be valid and canonical.
// We may want to re-visit this if we end up wanting to handle local/remote/merged interchangably.
impl Store {
  ///
  /// Make a store which only uses its local storage.
  ///
  pub fn local_only<P: AsRef<Path>>(path: P) -> Result<Store, String> {
    Ok(Store {
      local: local::ByteStore::new(path)?,
      remote: None,
    })
  }

  ///
  /// Make a store which uses local storage, and if it is missing a value which it tries to load,
  /// will attempt to back-fill its local storage from a remote CAS.
  ///
  pub fn with_remote<P: AsRef<Path>>(
    path: P,
    cas_addresses: &[String],
    instance_name: Option<String>,
    root_ca_certs: &Option<Vec<u8>>,
    oauth_bearer_token: Option<String>,
    thread_count: usize,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
    backoff_config: BackoffConfig,
    rpc_retries: usize,
    futures_timer_thread: futures_timer::TimerHandle,
  ) -> Result<Store, String> {
    Ok(Store {
      local: local::ByteStore::new(path)?,
      remote: Some(remote::ByteStore::new(
        cas_addresses,
        instance_name,
        root_ca_certs,
        oauth_bearer_token,
        thread_count,
        chunk_size_bytes,
        upload_timeout,
        backoff_config,
        rpc_retries,
        futures_timer_thread,
      )?),
    })
  }

  // This default is also hard-coded into the Python options code in global_options.py
  pub fn default_path() -> PathBuf {
    match dirs::home_dir() {
      Some(home_dir) => home_dir.join(".cache").join("pants").join("lmdb_store"),
      None => panic!("Could not find home dir"),
    }
  }

  ///
  /// Store a file locally.
  ///
  pub fn store_file_bytes(&self, bytes: Bytes, initial_lease: bool) -> BoxFuture<Digest, String> {
    self
      .local
      .store_bytes(EntryType::File, bytes, initial_lease)
      .to_boxed()
  }

  ///
  /// Loads the bytes of the file with the passed fingerprint from the local store and back-fill
  /// from remote when necessary and possible (i.e. when remote is configured), and returns the
  /// result of applying f to that value.
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
  /// Save the bytes of the Directory proto locally, without regard for any of the
  /// contents of any FileNodes or DirectoryNodes therein (i.e. does not require that its
  /// children are already stored).
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
    )
    .and_then(move |bytes| {
      local.store_bytes(EntryType::Directory, Bytes::from(bytes), initial_lease)
    })
    .to_boxed()
  }

  ///
  /// Loads a directory proto from the local store, back-filling from remote if necessary.
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

  ///
  /// Loads bytes from remote cas if required and possible (i.e. if remote is configured). Takes
  /// two functions f_local and f_remote. These functions are any validation or transformations you
  /// want to perform on the bytes received from the local and remote cas (if remote is configured).
  ///
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
      .load_bytes_with(entry_type, digest, f_local)
      .and_then(
        move |maybe_local_value| match (maybe_local_value, maybe_remote) {
          (Some(value_result), _) => future::done(value_result.map(Some)).to_boxed(),
          (None, None) => future::ok(None).to_boxed(),
          (None, Some(remote)) => remote
            .load_bytes_with(entry_type, digest, move |bytes: Bytes| bytes)
            .and_then(move |maybe_bytes: Option<Bytes>| match maybe_bytes {
              Some(bytes) => future::done(f_remote(bytes.clone()))
                .and_then(move |value| {
                  local
                    .store_bytes(entry_type, bytes, true)
                    .and_then(move |stored_digest| {
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
  /// Returns a structure with the summary of operations.
  ///
  pub fn ensure_remote_has_recursive(
    &self,
    digests: Vec<Digest>,
  ) -> BoxFuture<UploadSummary, String> {
    let start_time = Instant::now();

    let remote = if let Some(ref remote) = self.remote {
      remote
    } else {
      return future::err("Cannot ensure remote has blobs without a remote".to_owned()).to_boxed();
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
          return future::err(format!("Failed to upload digest {:?}: Not found", digest))
            .to_boxed();
        }
        Err(err) => {
          return future::err(format!("Failed to upload digest {:?}: {:?}", digest, err))
            .to_boxed();
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
      .and_then(move |ingested_digests| {
        if Store::upload_is_faster_than_checking_whether_to_upload(&ingested_digests) {
          return future::ok((ingested_digests.keys().cloned().collect(), ingested_digests))
            .to_boxed();
        }
        let request = remote.find_missing_blobs_request(ingested_digests.keys());
        let f = remote.list_missing_digests(request);
        f.map(move |digests_to_upload| (digests_to_upload, ingested_digests))
          .to_boxed()
      })
      .and_then(move |(digests_to_upload, ingested_digests)| {
        future::join_all(
          digests_to_upload
            .into_iter()
            .map(|digest| {
              let entry_type = ingested_digests[&digest];
              let remote = remote2.clone();
              local
                .load_bytes_with(entry_type, digest, move |bytes| remote.store_bytes(bytes))
                .and_then(move |maybe_future| match maybe_future {
                  Some(future) => Ok(future),
                  None => Err(format!("Failed to upload digest {:?}: Not found", digest)),
                })
            })
            .collect::<Vec<_>>(),
        )
        .and_then(future::join_all)
        .map(|uploaded_digests| (uploaded_digests, ingested_digests))
      })
      .map(move |(uploaded_digests, ingested_digests)| {
        let ingested_file_sizes = ingested_digests.iter().map(|(digest, _)| digest.1);
        let uploaded_file_sizes = uploaded_digests.iter().map(|digest| digest.1);

        UploadSummary {
          ingested_file_count: ingested_file_sizes.len(),
          ingested_file_bytes: ingested_file_sizes.sum(),
          uploaded_file_count: uploaded_file_sizes.len(),
          uploaded_file_bytes: uploaded_file_sizes.sum(),
          upload_wall_time: start_time.elapsed(),
        }
      })
      .to_boxed()
  }

  ///
  /// Download a directory from Remote ByteStore recursively to the local one. Called only with the
  /// Digest of a Directory.
  ///
  pub fn ensure_local_has_recursive_directory(&self, dir_digest: Digest) -> BoxFuture<(), String> {
    let store = self.clone();
    self
      .load_directory(dir_digest)
      .and_then(move |directory_opt| {
        directory_opt.ok_or_else(|| format!("Could not read dir with digest {:?}", dir_digest))
      })
      .and_then(move |directory| {
        // Traverse the files within directory
        let file_futures = directory
          .get_files()
          .iter()
          .map(|file_node| {
            let file_digest = try_future!(file_node.get_digest().into());
            store.load_bytes_with(EntryType::File, file_digest, |_| Ok(()), |_| Ok(()))
          })
          .collect::<Vec<_>>();

        // Recursively call with sub-directories
        let directory_futures = directory
          .get_directories()
          .iter()
          .map(move |child_dir| {
            let child_digest = try_future!(child_dir.get_digest().into());
            store.ensure_local_has_recursive_directory(child_digest)
          })
          .collect::<Vec<_>>();
        future::join_all(file_futures)
          .join(future::join_all(directory_futures))
          .map(|_| ())
      })
      .to_boxed()
  }

  pub fn lease_all<'a, Ds: Iterator<Item = &'a Digest>>(&self, digests: Ds) -> Result<(), String> {
    self.local.lease_all(digests)
  }

  pub fn garbage_collect(
    &self,
    target_size_bytes: usize,
    shrink_behavior: ShrinkBehavior,
  ) -> Result<(), String> {
    match self.local.shrink(target_size_bytes, shrink_behavior) {
      Ok(size) => {
        if size > target_size_bytes {
          Err(format!(
            "Garbage collection attempted to target {} bytes but could only shrink to {} bytes",
            target_size_bytes, size
          ))
        } else {
          Ok(())
        }
      }
      Err(err) => Err(format!("Garbage collection failed: {:?}", err)),
    }
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
    self
      .walk(digest, |_, _, digest, directory| {
        let mut digest_types = Vec::new();
        digest_types.push((digest, EntryType::Directory));
        for file in directory.get_files() {
          digest_types.push((try_future!(file.get_digest().into()), EntryType::File));
        }
        future::ok(digest_types).to_boxed()
      })
      .map(|digest_pairs_per_directory| {
        Iterator::flatten(digest_pairs_per_directory.into_iter().map(Vec::into_iter)).collect()
      })
      .to_boxed()
  }

  ///
  /// Lays out the directory and all of its contents (files and directories) on disk so that a
  /// process which uses the directory structure can run.
  ///
  pub fn materialize_directory(
    &self,
    destination: PathBuf,
    digest: Digest,
  ) -> BoxFuture<(), String> {
    try_future!(super::safe_create_dir_all(&destination));
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
          .and_then(|mut f| {
            f.write_all(&bytes)?;
            // See `materialize_directory`, but we fundamentally materialize files for other
            // processes to read; as such, we must ensure data is flushed to disk and visible
            // to them as opposed to just our process.
            f.sync_all()
          })
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
  pub fn contents_for_directory(&self, digest: Digest) -> BoxFuture<Vec<FileContent>, String> {
    self
      .walk(digest, |store, path_so_far, _, directory| {
        future::join_all(
          directory
            .get_files()
            .iter()
            .map(move |file_node| {
              let path = path_so_far.join(file_node.get_name());
              store
                .load_file_bytes_with(try_future!(file_node.get_digest().into()), |b| b)
                .and_then(move |maybe_bytes| {
                  maybe_bytes
                    .ok_or_else(|| format!("Couldn't find file contents for {:?}", path))
                    .map(|content| FileContent { path, content })
                })
                .to_boxed()
            })
            .collect::<Vec<_>>(),
        )
        .to_boxed()
      })
      .map(|file_contents_per_directory| {
        let mut vec =
          Iterator::flatten(file_contents_per_directory.into_iter().map(Vec::into_iter))
            .collect::<Vec<_>>();
        vec.sort_by(|l, r| l.path.cmp(&r.path));
        vec
      })
      .to_boxed()
  }

  ///
  /// Given the Digest for a Directory, recursively walk the Directory, calling the given function
  /// with the path so far, and the new Directory.
  ///
  /// The recursive walk will proceed concurrently, so if order matters, a caller should sort the
  /// output after the call.
  ///
  pub fn walk<
    T: Send + 'static,
    F: Fn(
        &Store,
        &PathBuf,
        Digest,
        &bazel_protos::remote_execution::Directory,
      ) -> BoxFuture<T, String>
      + Send
      + Sync
      + 'static,
  >(
    &self,
    digest: Digest,
    f: F,
  ) -> BoxFuture<Vec<T>, String> {
    let f = Arc::new(f);
    let accumulator = Arc::new(Mutex::new(Vec::new()));
    self
      .walk_helper(digest, PathBuf::new(), f, accumulator.clone())
      .map(|()| {
        Arc::try_unwrap(accumulator)
          .unwrap_or_else(|_| panic!("walk_helper violated its contract."))
          .into_inner()
      })
      .to_boxed()
  }

  fn walk_helper<
    T: Send + 'static,
    F: Fn(
        &Store,
        &PathBuf,
        Digest,
        &bazel_protos::remote_execution::Directory,
      ) -> BoxFuture<T, String>
      + Send
      + Sync
      + 'static,
  >(
    &self,
    digest: Digest,
    path_so_far: PathBuf,
    f: Arc<F>,
    accumulator: Arc<Mutex<Vec<T>>>,
  ) -> BoxFuture<(), String> {
    let store = self.clone();
    self
      .load_directory(digest)
      .and_then(move |maybe_directory| match maybe_directory {
        Some(directory) => {
          let result_for_directory = f(&store, &path_so_far, digest, &directory);
          result_for_directory
            .and_then(move |r| {
              {
                let mut accumulator = accumulator.lock();
                accumulator.push(r);
              }
              future::join_all(
                directory
                  .get_directories()
                  .iter()
                  .map(move |dir_node| {
                    let subdir_digest = try_future!(dir_node.get_digest().into());
                    let path = path_so_far.join(dir_node.get_name());
                    store.walk_helper(subdir_digest, path, f.clone(), accumulator.clone())
                  })
                  .collect::<Vec<_>>(),
              )
              .map(|_| ())
            })
            .to_boxed()
        }
        None => future::err(format!("Could not walk unknown directory: {:?}", digest)).to_boxed(),
      })
      .to_boxed()
  }
}

// Only public for testing.
#[derive(Copy, Clone, Debug, Eq, Hash, PartialEq, Ord, PartialOrd)]
pub enum EntryType {
  Directory,
  File,
}

mod local {
  use super::{EntryType, ShrinkBehavior};

  use boxfuture::{BoxFuture, Boxable};
  use bytes::Bytes;
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::future::{self, Future};
  use hashing::{Digest, Fingerprint};
  use lmdb::Error::{KeyExist, NotFound};
  use lmdb::{
    self, Cursor, Database, DatabaseFlags, Environment, EnvironmentCopyFlags, EnvironmentFlags,
    RwTransaction, Transaction, WriteFlags,
  };
  use log::{error, trace};
  use sha2::Sha256;
  use std;
  use std::collections::{BinaryHeap, HashMap};
  use std::fmt;
  use std::path::{Path, PathBuf};
  use std::sync::Arc;
  use std::time;
  use tempfile::TempDir;

  use super::super::EMPTY_DIGEST;
  use super::MAX_LOCAL_STORE_SIZE_BYTES;

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
  }

  impl ByteStore {
    pub fn new<P: AsRef<Path>>(path: P) -> Result<ByteStore, String> {
      let root = path.as_ref();
      let files_root = root.join("files");
      let directories_root = root.join("directories");
      Ok(ByteStore {
        inner: Arc::new(InnerStore {
          file_dbs: ShardedLmdb::new(files_root.clone()).map(Arc::new),
          directory_dbs: ShardedLmdb::new(directories_root.clone()).map(Arc::new),
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

    pub fn lease_all<'a, Ds: Iterator<Item = &'a Digest>>(
      &self,
      digests: Ds,
    ) -> Result<(), String> {
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
    ) -> BoxFuture<Digest, String> {
      let dbs = match entry_type {
        EntryType::Directory => self.inner.directory_dbs.clone(),
        EntryType::File => self.inner.file_dbs.clone(),
      };

      let bytestore = self.clone();
      futures::future::poll_fn(move || {
        tokio_threadpool::blocking(|| {
          let fingerprint = {
            let mut hasher = Sha256::default();
            hasher.input(&bytes);
            Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
          };
          let digest = Digest(fingerprint, bytes.len());

          let (env, content_database, lease_database) = dbs.clone()?.get(&fingerprint);
          let put_res = env.begin_rw_txn().and_then(|mut txn| {
            txn.put(
              content_database,
              &fingerprint,
              &bytes,
              WriteFlags::NO_OVERWRITE,
            )?;
            if initial_lease {
              bytestore.lease(
                lease_database,
                &fingerprint,
                Self::default_lease_until_secs_since_epoch(),
                &mut txn,
              )?;
            }
            txn.commit()
          });

          match put_res {
            Ok(()) => Ok(digest),
            Err(KeyExist) => Ok(digest),
            Err(err) => Err(format!("Error storing digest {:?}: {}", digest, err)),
          }
        })
      })
      .then(|blocking_result| match blocking_result {
        Ok(v) => v,
        Err(blocking_err) => Err(format!(
          "Unable to run blocking task to store_bytes in local ByteStore on tokio runtime: {}",
          blocking_err
        )),
      })
      .to_boxed()
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

      futures::future::poll_fn(move || tokio_threadpool::blocking( || {
          let (env, db, _) = dbs.clone()?.get(&digest.0);
          let ro_txn = env
            .begin_ro_txn()
            .map_err(|err| format!("Failed to begin read transaction: {}", err));
          ro_txn.and_then(|txn| match txn.get(db, &digest.0) {
            Ok(bytes) => {
              if bytes.len() == digest.1 {
                Ok(Some(f(Bytes::from(bytes))))
              } else {
                error!("Got hash collision reading from store - digest {:?} was requested, but retrieved bytes with that fingerprint had length {}. Congratulations, you may have broken sha256! Underlying bytes: {:?}", digest, bytes.len(), bytes);
                Ok(None)
              }
            }
            Err(NotFound) => Ok(None),
            Err(err) => Err(format!("Error loading digest {:?}: {}", digest, err,)),
          })
        })).then(|blocking_result| {
        match blocking_result {
          Ok(v) => v,
          Err(blocking_err) => Err(format!("Unable to run blocking task to load_bytes in local ByteStore on tokio runtime: {}", blocking_err)),
        }
      }).to_boxed()
    }
  }

  // Each LMDB directory can have at most one concurrent writer.
  // We use this type to shard storage into 16 LMDB directories, based on the first 4 bits of the
  // fingerprint being stored, so that we can write to them in parallel.
  #[derive(Clone)]
  struct ShardedLmdb {
    // First Database is content, second is leases.
    lmdbs: HashMap<u8, (Arc<Environment>, Database, Database)>,
    root_path: PathBuf,
  }

  impl ShardedLmdb {
    pub fn new(root_path: PathBuf) -> Result<ShardedLmdb, String> {
      trace!("Initializing ShardedLmdb at root {:?}", root_path);
      let mut lmdbs = HashMap::new();

      for (env, dir, fingerprint_prefix) in ShardedLmdb::envs(&root_path)? {
        trace!("Making ShardedLmdb content database for {:?}", dir);
        let content_database = env
          .create_db(Some("content"), DatabaseFlags::empty())
          .map_err(|e| {
            format!(
              "Error creating/opening content database at {:?}: {}",
              dir, e
            )
          })?;

        trace!("Making ShardedLmdb lease database for {:?}", dir);
        let lease_database = env
          .create_db(Some("leases"), DatabaseFlags::empty())
          .map_err(|e| {
            format!(
              "Error creating/opening content database at {:?}: {}",
              dir, e
            )
          })?;

        lmdbs.insert(
          fingerprint_prefix,
          (Arc::new(env), content_database, lease_database),
        );
      }

      Ok(ShardedLmdb { lmdbs, root_path })
    }

    fn envs(root_path: &Path) -> Result<Vec<(Environment, PathBuf, u8)>, String> {
      let mut envs = Vec::with_capacity(0x10);
      for b in 0x00..0x10 {
        let fingerprint_prefix = b << 4;
        let mut dirname = String::new();
        fmt::Write::write_fmt(&mut dirname, format_args!("{:x}", fingerprint_prefix)).unwrap();
        let dirname = dirname[0..1].to_owned();
        let dir = root_path.join(dirname);
        super::super::safe_create_dir_all(&dir)
          .map_err(|err| format!("Error making directory for store at {:?}: {:?}", dir, err))?;
        envs.push((ShardedLmdb::make_env(&dir)?, dir, fingerprint_prefix));
      }
      Ok(envs)
    }

    fn make_env(dir: &Path) -> Result<Environment, String> {
      Environment::new()
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
        .set_flags(EnvironmentFlags::NO_SYNC | EnvironmentFlags::NO_TLS)
        // 2 DBs; one for file contents, one for leases.
        .set_max_dbs(2)
        .set_map_size(MAX_LOCAL_STORE_SIZE_BYTES)
        .open(dir)
        .map_err(|e| format!("Error making env for store at {:?}: {}", dir, e))
    }

    // First Database is content, second is leases.
    pub fn get(&self, fingerprint: &Fingerprint) -> (Arc<Environment>, Database, Database) {
      self.lmdbs[&(fingerprint.0[0] & 0xF0)].clone()
    }

    pub fn all_lmdbs(&self) -> Vec<(Arc<Environment>, Database, Database)> {
      self.lmdbs.values().cloned().collect()
    }

    pub fn compact(&self) -> Result<(), String> {
      for (env, old_dir, _) in ShardedLmdb::envs(&self.root_path)? {
        let new_dir = TempDir::new_in(old_dir.parent().unwrap()).expect("TODO");
        env
          .copy(new_dir.path(), EnvironmentCopyFlags::COMPACT)
          .map_err(|e| {
            format!(
              "Error copying store from {:?} to {:?}: {}",
              old_dir,
              new_dir.path(),
              e
            )
          })?;
        std::fs::remove_dir_all(&old_dir)
          .map_err(|e| format!("Error removing old store at {:?}: {}", old_dir, e))?;
        std::fs::rename(&new_dir.path(), &old_dir).map_err(|e| {
          format!(
            "Error replacing {:?} with {:?}: {}",
            old_dir,
            new_dir.path(),
            e
          )
        })?;

        // Prevent the tempdir from being deleted on drop.
        std::mem::drop(new_dir);
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
        block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false)),
        Ok(testdata.digest())
      );
    }

    #[test]
    fn save_file_is_idempotent() {
      let dir = TempDir::new().unwrap();

      let testdata = TestData::roland();
      block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false))
        .unwrap();
      assert_eq!(
        block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false)),
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
        block_on(new_store(dir.path()).store_bytes(EntryType::Directory, testdir.bytes(), false)),
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

      block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false))
        .unwrap();

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

    pub fn new_store<P: AsRef<Path>>(dir: P) -> ByteStore {
      ByteStore::new(dir).unwrap()
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
}

mod remote {
  use super::{BackoffConfig, EntryType};

  use bazel_protos;
  use boxfuture::{BoxFuture, Boxable};
  use bytes::{Bytes, BytesMut};
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::{self, future, Future, IntoFuture, Sink, Stream};
  use grpcio;
  use hashing::{Digest, Fingerprint};
  use serverset::{Retry, Serverset};
  use sha2::Sha256;
  use std::cmp::min;
  use std::collections::HashSet;
  use std::sync::Arc;
  use std::time::Duration;
  use uuid;

  #[derive(Clone)]
  pub struct ByteStore {
    instance_name: Option<String>,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
    rpc_attempts: usize,
    env: Arc<grpcio::Environment>,
    serverset: Serverset<grpcio::Channel>,
    authorization_header: Option<String>,
  }

  impl ByteStore {
    pub fn new(
      cas_addresses: &[String],
      instance_name: Option<String>,
      root_ca_certs: &Option<Vec<u8>>,
      oauth_bearer_token: Option<String>,
      thread_count: usize,
      chunk_size_bytes: usize,
      upload_timeout: Duration,
      backoff_config: BackoffConfig,
      rpc_retries: usize,
      futures_timer_thread: futures_timer::TimerHandle,
    ) -> Result<ByteStore, String> {
      let env = Arc::new(grpcio::Environment::new(thread_count));

      let channels = cas_addresses
        .iter()
        .map(|cas_address| {
          let builder = grpcio::ChannelBuilder::new(env.clone());
          if let Some(ref root_ca_certs) = root_ca_certs {
            let creds = grpcio::ChannelCredentialsBuilder::new()
              .root_cert(root_ca_certs.clone())
              .build();
            builder.secure_connect(cas_address, creds)
          } else {
            builder.connect(cas_address)
          }
        })
        .collect();

      let serverset = Serverset::new(channels, backoff_config, futures_timer_thread)?;

      Ok(ByteStore {
        instance_name,
        chunk_size_bytes,
        upload_timeout,
        rpc_attempts: rpc_retries + 1,
        env,
        serverset,
        authorization_header: oauth_bearer_token.map(|t| format!("Bearer {}", t)),
      })
    }

    fn with_byte_stream_client<
      Value: Send + 'static,
      Fut: Future<Item = Value, Error = String>,
      IntoFut: IntoFuture<Future = Fut, Item = Value, Error = String>,
      F: Fn(bazel_protos::bytestream_grpc::ByteStreamClient) -> IntoFut
        + Send
        + Sync
        + Clone
        + 'static,
    >(
      &self,
      f: F,
    ) -> impl Future<Item = Value, Error = String> {
      Retry(self.serverset.clone()).all_errors_immediately(
        move |channel| {
          f(bazel_protos::bytestream_grpc::ByteStreamClient::new(
            channel,
          ))
        },
        self.rpc_attempts,
      )
    }

    fn with_cas_client<
      Value: Send + 'static,
      Fut: Future<Item = Value, Error = String>,
      IntoFut: IntoFuture<Future = Fut, Item = Value, Error = String>,
      F: Fn(bazel_protos::remote_execution_grpc::ContentAddressableStorageClient) -> IntoFut
        + Send
        + Sync
        + Clone
        + 'static,
    >(
      &self,
      f: F,
    ) -> impl Future<Item = Value, Error = String> {
      Retry(self.serverset.clone()).all_errors_immediately(
        move |channel| {
          f(bazel_protos::remote_execution_grpc::ContentAddressableStorageClient::new(channel))
        },
        self.rpc_attempts,
      )
    }

    fn call_option(&self) -> grpcio::CallOption {
      let mut call_option = grpcio::CallOption::default();
      if let Some(ref authorization_header) = self.authorization_header {
        let mut builder = grpcio::MetadataBuilder::with_capacity(1);
        builder
          .add_str("authorization", &authorization_header)
          .unwrap();
        call_option = call_option.headers(builder.build());
      }
      call_option
    }

    pub fn store_bytes(&self, bytes: Bytes) -> BoxFuture<Digest, String> {
      let mut hasher = Sha256::default();
      hasher.input(&bytes);
      let fingerprint = Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice());
      let len = bytes.len();
      let digest = Digest(fingerprint, len);
      let resource_name = format!(
        "{}/uploads/{}/blobs/{}/{}",
        self.instance_name.clone().unwrap_or_default(),
        uuid::Uuid::new_v4(),
        digest.0,
        digest.1,
      );
      let store = self.clone();
      self
        .with_byte_stream_client(move |client| {
          match client
            .write_opt(store.call_option().timeout(store.upload_timeout))
            .map(|v| (v, client))
          {
            Err(err) => future::err(format!(
              "Error attempting to connect to upload digest {:?}: {:?}",
              digest, err
            ))
            .to_boxed(),
            Ok(((sender, receiver), _client)) => {
              let chunk_size_bytes = store.chunk_size_bytes;
              let resource_name = resource_name.clone();
              let bytes = bytes.clone();
              let stream = futures::stream::unfold::<
                _,
                _,
                futures::future::FutureResult<_, grpcio::Error>,
                _,
              >((0, false), move |(offset, has_sent_any)| {
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
              });

              sender
                .send_all(stream)
                .map(|_| ())
                .or_else(move |e| {
                  match e {
                    // Some implementations of the remote execution API early-return if the blob has
                    // been concurrently uploaded by another client. In this case, they return a
                    // WriteResponse with a committed_size equal to the digest's entire size before
                    // closing the stream.
                    // Because the server then closes the stream, the client gets an RpcFinished
                    // error in this case. We ignore this, and will later on verify that the
                    // committed_size we received from the server is equal to the expected one. If
                    // these are not equal, the upload will be considered a failure at that point.
                    // Whether this type of response will become part of the official API is up for
                    // discussion: see
                    // https://groups.google.com/d/topic/remote-execution-apis/NXUe3ItCw68/discussion.
                    grpcio::Error::RpcFinished(None) => Ok(()),
                    e => Err(format!(
                      "Error attempting to upload digest {:?}: {:?}",
                      digest, e
                    )),
                  }
                })
                .and_then(move |()| {
                  receiver.map_err(move |e| {
                    format!(
                      "Error from server when uploading digest {:?}: {:?}",
                      digest, e
                    )
                  })
                })
                .and_then(move |received| {
                  if received.get_committed_size() == len as i64 {
                    Ok(digest)
                  } else {
                    Err(format!(
                      "Uploading file with digest {:?}: want commited size {} but got {}",
                      digest,
                      len,
                      received.get_committed_size()
                    ))
                  }
                })
                .to_boxed()
            }
          }
        })
        .to_boxed()
    }

    pub fn load_bytes_with<T: Send + 'static, F: Fn(Bytes) -> T + Send + Sync + Clone + 'static>(
      &self,
      _entry_type: EntryType,
      digest: Digest,
      f: F,
    ) -> BoxFuture<Option<T>, String> {
      let store = self.clone();
      self
        .with_byte_stream_client(move |client| {
          match client
            .read_opt(
              &{
                let mut req = bazel_protos::bytestream::ReadRequest::new();
                req.set_resource_name(format!(
                  "{}/blobs/{}/{}",
                  store.instance_name.clone().unwrap_or_default(),
                  digest.0,
                  digest.1
                ));
                req.set_read_offset(0);
                // 0 means no limit.
                req.set_read_limit(0);
                req
              },
              store.call_option(),
            )
            .map(|stream| (stream, client))
          {
            Ok((stream, client)) => {
              let f = f.clone();
              // We shouldn't have to pass around the client here, it's a workaround for
              // https://github.com/pingcap/grpc-rs/issues/123
              future::ok(client)
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
            ))
            .to_boxed(),
          }
        })
        .to_boxed()
    }

    ///
    /// Given a collection of Digests (digests),
    /// returns the set of digests from that collection not present in the CAS.
    ///
    pub fn list_missing_digests(
      &self,
      request: bazel_protos::remote_execution::FindMissingBlobsRequest,
    ) -> impl Future<Item = HashSet<Digest>, Error = String> {
      let store = self.clone();
      self.with_cas_client(move |client| {
        client
          .find_missing_blobs_opt(&request, store.call_option())
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
      })
    }

    pub(super) fn find_missing_blobs_request<'a, Digests: Iterator<Item = &'a Digest>>(
      &self,
      digests: Digests,
    ) -> bazel_protos::remote_execution::FindMissingBlobsRequest {
      let mut request = bazel_protos::remote_execution::FindMissingBlobsRequest::new();
      if let Some(ref instance_name) = self.instance_name {
        request.set_instance_name(instance_name.clone());
      }
      for digest in digests {
        request.mut_blob_digests().push(digest.into());
      }
      request
    }
  }

  #[cfg(test)]
  mod tests {
    use super::super::EntryType;
    use super::ByteStore;
    use bytes::Bytes;
    use futures_timer::TimerHandle;
    use hashing::Digest;
    use mock::StubCAS;
    use serverset::BackoffConfig;
    use std::collections::HashSet;
    use std::time::Duration;
    use testutil::data::{TestData, TestDirectory};

    use super::super::tests::{
      big_file_bytes, big_file_digest, big_file_fingerprint, block_on, new_cas,
    };

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
      )
      .expect_err("Want error");
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
        block_on(store.store_bytes(testdata.bytes())),
        Ok(testdata.digest())
      );

      let blobs = cas.blobs.lock();
      assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));
    }

    #[test]
    fn write_file_multiple_chunks() {
      let cas = StubCAS::empty();

      let store = ByteStore::new(
        &[cas.address()],
        None,
        &None,
        None,
        1,
        10 * 1024,
        Duration::from_secs(5),
        BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
        1,
        TimerHandle::default(),
      )
      .unwrap();

      let all_the_henries = big_file_bytes();

      let fingerprint = big_file_fingerprint();

      assert_eq!(
        block_on(store.store_bytes(all_the_henries.clone())),
        Ok(big_file_digest())
      );

      let blobs = cas.blobs.lock();
      assert_eq!(blobs.get(&fingerprint), Some(&all_the_henries));

      let write_message_sizes = cas.write_message_sizes.lock();
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
        block_on(store.store_bytes(empty_file.bytes())),
        Ok(empty_file.digest())
      );

      let blobs = cas.blobs.lock();
      assert_eq!(
        blobs.get(&empty_file.fingerprint()),
        Some(&empty_file.bytes())
      );
    }

    #[test]
    fn write_file_errors() {
      let cas = StubCAS::always_errors();

      let store = new_byte_store(&cas);
      let error = block_on(store.store_bytes(TestData::roland().bytes())).expect_err("Want error");
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
        &[String::from("doesnotexist.example")],
        None,
        &None,
        None,
        1,
        10 * 1024 * 1024,
        Duration::from_secs(1),
        BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
        1,
        TimerHandle::default(),
      )
      .unwrap();
      let error = block_on(store.store_bytes(TestData::roland().bytes())).expect_err("Want error");
      assert!(
        error.contains("Error attempting to upload digest"),
        format!("Bad error message, got: {}", error)
      );
    }

    #[test]
    fn list_missing_digests_none_missing() {
      let cas = new_cas(1024);

      let store = new_byte_store(&cas);
      assert_eq!(
        block_on(store.list_missing_digests(
          store.find_missing_blobs_request(vec![TestData::roland().digest()].iter())
        )),
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
        block_on(store.list_missing_digests(store.find_missing_blobs_request(vec![digest].iter()))),
        Ok(digest_set)
      );
    }

    #[test]
    fn list_missing_digests_error() {
      let cas = StubCAS::always_errors();

      let store = new_byte_store(&cas);

      let error = block_on(store.list_missing_digests(
        store.find_missing_blobs_request(vec![TestData::roland().digest()].iter()),
      ))
      .expect_err("Want error");
      assert!(
        error.contains("StubCAS is configured to always fail"),
        format!("Bad error message, got: {}", error)
      );
    }

    #[test]
    fn reads_from_multiple_cas_servers() {
      let roland = TestData::roland();
      let catnip = TestData::catnip();

      let cas1 = StubCAS::builder().file(&roland).file(&catnip).build();
      let cas2 = StubCAS::builder().file(&roland).file(&catnip).build();

      let store = ByteStore::new(
        &[cas1.address(), cas2.address()],
        None,
        &None,
        None,
        1,
        10 * 1024 * 1024,
        Duration::from_secs(1),
        BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
        1,
        TimerHandle::default(),
      )
      .unwrap();

      assert_eq!(
        load_file_bytes(&store, roland.digest()),
        Ok(Some(roland.bytes()))
      );

      assert_eq!(
        load_file_bytes(&store, catnip.digest()),
        Ok(Some(catnip.bytes()))
      );

      assert_eq!(cas1.read_request_count(), 1);
      assert_eq!(cas2.read_request_count(), 1);
    }

    fn new_byte_store(cas: &StubCAS) -> ByteStore {
      ByteStore::new(
        &[cas.address()],
        None,
        &None,
        None,
        1,
        10 * 1024 * 1024,
        Duration::from_secs(1),
        BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
        1,
        TimerHandle::default(),
      )
      .unwrap()
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
  }
}

#[cfg(test)]
mod tests {
  use super::{local, EntryType, FileContent, Store, UploadSummary};

  use bazel_protos;
  use bytes::Bytes;
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::Future;
  use futures_timer::TimerHandle;
  use hashing::{Digest, Fingerprint};
  use mock::StubCAS;
  use protobuf::Message;
  use serverset::BackoffConfig;
  use sha2::Sha256;
  use std;
  use std::collections::HashMap;
  use std::fs::File;
  use std::io::Read;
  use std::os::unix::fs::PermissionsExt;
  use std::path::{Path, PathBuf};
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
    )
    .expect("Error opening all_the_henries");
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
    block_on(store.load_file_bytes_with(digest, |bytes| bytes))
  }

  ///
  /// Create a StubCas with a file and a directory inside.
  ///
  pub fn new_cas(chunk_size_bytes: usize) -> StubCAS {
    StubCAS::builder()
      .chunk_size_bytes(chunk_size_bytes)
      .file(&TestData::roland())
      .directory(&TestDirectory::containing_roland())
      .build()
  }

  ///
  /// Create a new local store with whatever was already serialized in dir.
  ///
  fn new_local_store<P: AsRef<Path>>(dir: P) -> Store {
    Store::local_only(dir).expect("Error creating local store")
  }

  ///
  /// Create a new store with a remote CAS.
  ///
  fn new_store<P: AsRef<Path>>(dir: P, cas_address: String) -> Store {
    Store::with_remote(
      dir,
      &[cas_address],
      None,
      &None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      TimerHandle::default(),
    )
    .unwrap()
  }

  #[test]
  fn load_file_prefers_local() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    block_on(local::tests::new_store(dir.path()).store_bytes(
      EntryType::File,
      testdata.bytes(),
      false,
    ))
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

    block_on(local::tests::new_store(dir.path()).store_bytes(
      EntryType::Directory,
      testdir.bytes(),
      false,
    ))
    .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
      block_on(new_store(dir.path(), cas.address()).load_directory(testdir.digest())),
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
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), testdata.digest()),
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
      block_on(new_store(dir.path(), cas.address()).load_directory(testdir.digest())),
      Ok(Some(testdir.directory()))
    );
    assert_eq!(1, cas.read_request_count());
    assert_eq!(
      local::tests::load_directory_proto_bytes(
        &local::tests::new_store(dir.path()),
        testdir.digest(),
      ),
      Ok(Some(testdir.bytes()))
    );
  }

  #[test]
  fn load_recursive_directory() {
    let dir = TempDir::new().unwrap();

    let roland = TestData::roland();
    let catnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland();
    let testdir_digest = testdir.digest();
    let testdir_directory = testdir.directory();
    let recursive_testdir = TestDirectory::recursive();
    let recursive_testdir_directory = recursive_testdir.directory();
    let recursive_testdir_digest = recursive_testdir.digest();

    let cas = StubCAS::builder()
      .file(&roland)
      .file(&catnip)
      .directory(&testdir)
      .directory(&recursive_testdir)
      .build();

    block_on(
      new_store(dir.path(), cas.address())
        .ensure_local_has_recursive_directory(recursive_testdir_digest),
    )
    .expect("Downloading recursive directory should have succeeded.");

    assert_eq!(
      load_file_bytes(&new_local_store(dir.path()), roland.digest()),
      Ok(Some(roland.bytes()))
    );
    assert_eq!(
      load_file_bytes(&new_local_store(dir.path()), catnip.digest()),
      Ok(Some(catnip.bytes()))
    );
    assert_eq!(
      block_on(new_local_store(dir.path()).load_directory(testdir_digest)),
      Ok(Some(testdir_directory))
    );
    assert_eq!(
      block_on(new_local_store(dir.path()).load_directory(recursive_testdir_digest)),
      Ok(Some(recursive_testdir_directory))
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
      block_on(
        new_store(dir.path(), cas.address())
          .load_directory(TestDirectory::containing_roland().digest())
      ),
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
    )
    .expect_err("Want error");
    assert!(
      cas.read_request_count() > 0,
      "Want read_request_count > 0 but got {}",
      cas.read_request_count()
    );
    assert!(
      error.contains("StubCAS is configured to always fail"),
      "Bad error message"
    );
  }

  #[test]
  fn load_directory_remote_error_is_error() {
    let dir = TempDir::new().unwrap();

    let cas = StubCAS::always_errors();
    let error =
      block_on(new_store(dir.path(), cas.address()).load_directory(TestData::roland().digest()))
        .expect_err("Want error");
    assert!(
      cas.read_request_count() > 0,
      "Want read_request_count > 0 but got {}",
      cas.read_request_count()
    );
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
    block_on(new_store(dir.path(), cas.address()).load_directory(testdata.digest()))
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_directory_proto_bytes(
        &local::tests::new_store(dir.path()),
        testdata.digest()
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

    let cas = StubCAS::builder()
      .unverified_content(
        non_canonical_directory_fingerprint.clone(),
        non_canonical_directory_bytes,
      )
      .build();
    block_on(new_store(dir.path(), cas.address()).load_directory(directory_digest.clone()))
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_directory_proto_bytes(
        &local::tests::new_store(dir.path()),
        directory_digest,
      ),
      Ok(None)
    );
  }

  #[test]
  fn wrong_remote_file_bytes_is_error() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let cas = StubCAS::builder()
      .unverified_content(
        testdata.fingerprint(),
        TestDirectory::containing_roland().bytes(),
      )
      .build();
    load_file_bytes(&new_store(dir.path(), cas.address()), testdata.digest())
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), testdata.digest()),
      Ok(None)
    );
  }

  #[test]
  fn wrong_remote_directory_bytes_is_error() {
    let dir = TempDir::new().unwrap();

    let testdir = TestDirectory::containing_dnalor();

    let cas = StubCAS::builder()
      .unverified_content(
        testdir.fingerprint(),
        TestDirectory::containing_roland().bytes(),
      )
      .build();
    load_file_bytes(&new_store(dir.path(), cas.address()), testdir.digest())
      .expect_err("Want error");

    assert_eq!(
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), testdir.digest()),
      Ok(None)
    );
  }

  #[test]
  fn expand_empty_directory() {
    let dir = TempDir::new().unwrap();

    let empty_dir = TestDirectory::empty();

    let expanded = block_on(new_local_store(dir.path()).expand_directory(empty_dir.digest()))
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

    block_on(new_local_store(dir.path()).record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");

    let expanded = block_on(new_local_store(dir.path()).expand_directory(testdir.digest()))
      .expect("Error expanding directory");
    let want: HashMap<Digest, EntryType> = vec![
      (testdir.digest(), EntryType::Directory),
      (roland.digest(), EntryType::File),
    ]
    .into_iter()
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

    block_on(new_local_store(dir.path()).record_directory(&recursive_testdir.directory(), false))
      .expect("Error storing directory locally");
    block_on(new_local_store(dir.path()).record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");

    let expanded =
      block_on(new_local_store(dir.path()).expand_directory(recursive_testdir.digest()))
        .expect("Error expanding directory");
    let want: HashMap<Digest, EntryType> = vec![
      (recursive_testdir.digest(), EntryType::Directory),
      (testdir.digest(), EntryType::Directory),
      (roland.digest(), EntryType::File),
      (catnip.digest(), EntryType::File),
    ]
    .into_iter()
    .collect();
    assert_eq!(expanded, want);
  }

  #[test]
  fn expand_missing_directory() {
    let dir = TempDir::new().unwrap();
    let digest = TestDirectory::containing_roland().digest();
    let error =
      block_on(new_local_store(dir.path()).expand_directory(digest)).expect_err("Want error");
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

    block_on(new_local_store(dir.path()).record_directory(&recursive_testdir.directory(), false))
      .expect("Error storing directory locally");

    let error = block_on(new_local_store(dir.path()).expand_directory(recursive_testdir.digest()))
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

    block_on(new_local_store(dir.path()).store_file_bytes(testdata.bytes(), false))
      .expect("Error storing file locally");

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

    block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![testdata.digest()]),
    )
    .expect("Error uploading file");

    assert_eq!(
      cas.blobs.lock().get(&testdata.fingerprint()),
      Some(&testdata.bytes())
    );
  }

  #[test]
  fn uploads_directories_recursively() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    block_on(new_local_store(dir.path()).record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");
    block_on(new_local_store(dir.path()).store_file_bytes(testdata.bytes(), false))
      .expect("Error storing file locally");

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);
    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

    block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![testdir.digest()]),
    )
    .expect("Error uploading directory");

    assert_eq!(
      cas.blobs.lock().get(&testdir.fingerprint()),
      Some(&testdir.bytes())
    );
    assert_eq!(
      cas.blobs.lock().get(&testdata.fingerprint()),
      Some(&testdata.bytes())
    );
  }

  #[test]
  fn uploads_files_recursively_when_under_three_digests_ignoring_items_already_in_cas() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    block_on(new_local_store(dir.path()).record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");
    block_on(new_local_store(dir.path()).store_file_bytes(testdata.bytes(), false))
      .expect("Error storing file locally");

    block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![testdata.digest()]),
    )
    .expect("Error uploading file");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
      cas.blobs.lock().get(&testdata.fingerprint()),
      Some(&testdata.bytes())
    );
    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

    block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![testdir.digest()]),
    )
    .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 3);
    assert_eq!(
      cas.blobs.lock().get(&testdir.fingerprint()),
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

    block_on(new_local_store(dir.path()).record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");
    block_on(new_local_store(dir.path()).store_file_bytes(roland.bytes(), false))
      .expect("Error storing file locally");
    block_on(new_local_store(dir.path()).store_file_bytes(catnip.bytes(), false))
      .expect("Error storing file locally");

    block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![roland.digest()]),
    )
    .expect("Error uploading big file");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
      cas.blobs.lock().get(&roland.fingerprint()),
      Some(&roland.bytes())
    );
    assert_eq!(cas.blobs.lock().get(&catnip.fingerprint()), None);
    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

    block_on(
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testdir.digest(), catnip.digest()]),
    )
    .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 3);
    assert_eq!(
      cas.blobs.lock().get(&catnip.fingerprint()),
      Some(&catnip.bytes())
    );
    assert_eq!(
      cas.blobs.lock().get(&testdir.fingerprint()),
      Some(&testdir.bytes())
    );
  }

  #[test]
  fn does_not_reupload_big_file_already_in_cas() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    block_on(new_local_store(dir.path()).store_file_bytes(extra_big_file_bytes(), false))
      .expect("Error storing file locally");

    block_on(
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![extra_big_file_digest()]),
    )
    .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
      cas.blobs.lock().get(&extra_big_file_fingerprint()),
      Some(&extra_big_file_bytes())
    );

    block_on(
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![extra_big_file_digest()]),
    )
    .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
      cas.blobs.lock().get(&extra_big_file_fingerprint()),
      Some(&extra_big_file_bytes())
    );
  }

  #[test]
  fn upload_missing_files() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testdata = TestData::roland();

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

    let error = block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![testdata.digest()]),
    )
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

    block_on(new_local_store(dir.path()).record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");

    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);
    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

    let error = block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![testdir.digest()]),
    )
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
  fn uploading_digest_with_wrong_size_is_error() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testdata = TestData::roland();

    block_on(new_local_store(dir.path()).store_file_bytes(testdata.bytes(), false))
      .expect("Error storing file locally");

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

    let wrong_digest = Digest(testdata.fingerprint(), testdata.len() + 1);

    block_on(new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![wrong_digest]))
      .expect_err("Expect error uploading file");

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);
  }

  #[test]
  fn instance_name_upload() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::builder()
      .instance_name("dark-tower".to_owned())
      .build();

    // 3 is enough digests to trigger a FindMissingBlobs request
    let testdir = TestDirectory::containing_roland_and_treats();

    block_on(new_local_store(dir.path()).record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");
    block_on(new_local_store(dir.path()).store_file_bytes(TestData::roland().bytes(), false))
      .expect("Error storing roland locally");
    block_on(new_local_store(dir.path()).store_file_bytes(TestData::catnip().bytes(), false))
      .expect("Error storing catnip locally");

    let store_with_remote = Store::with_remote(
      dir.path(),
      &[cas.address()],
      Some("dark-tower".to_owned()),
      &None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      TimerHandle::default(),
    )
    .unwrap();

    block_on(store_with_remote.ensure_remote_has_recursive(vec![testdir.digest()]))
      .expect("Error uploading");
  }

  #[test]
  fn instance_name_download() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::builder()
      .instance_name("dark-tower".to_owned())
      .file(&TestData::roland())
      .build();

    let store_with_remote = Store::with_remote(
      dir.path(),
      &[cas.address()],
      Some("dark-tower".to_owned()),
      &None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      TimerHandle::default(),
    )
    .unwrap();

    assert_eq!(
      block_on(store_with_remote.load_file_bytes_with(TestData::roland().digest(), |b| b)),
      Ok(Some(TestData::roland().bytes()))
    )
  }

  #[test]
  fn auth_upload() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::builder()
      .required_auth_token("Armory.Key".to_owned())
      .build();

    // 3 is enough digests to trigger a FindMissingBlobs request
    let testdir = TestDirectory::containing_roland_and_treats();

    block_on(new_local_store(dir.path()).record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");
    block_on(new_local_store(dir.path()).store_file_bytes(TestData::roland().bytes(), false))
      .expect("Error storing roland locally");
    block_on(new_local_store(dir.path()).store_file_bytes(TestData::catnip().bytes(), false))
      .expect("Error storing catnip locally");

    let store_with_remote = Store::with_remote(
      dir.path(),
      &[cas.address()],
      None,
      &None,
      Some("Armory.Key".to_owned()),
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      TimerHandle::default(),
    )
    .unwrap();

    block_on(store_with_remote.ensure_remote_has_recursive(vec![testdir.digest()]))
      .expect("Error uploading");
  }

  #[test]
  fn auth_download() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::builder()
      .required_auth_token("Armory.Key".to_owned())
      .file(&TestData::roland())
      .build();

    let store_with_remote = Store::with_remote(
      dir.path(),
      &[cas.address()],
      None,
      &None,
      Some("Armory.Key".to_owned()),
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      TimerHandle::default(),
    )
    .unwrap();

    assert_eq!(
      block_on(store_with_remote.load_file_bytes_with(TestData::roland().digest(), |b| b)),
      Ok(Some(TestData::roland().bytes()))
    )
  }

  #[test]
  fn materialize_missing_file() {
    let materialize_dir = TempDir::new().unwrap();
    let file = materialize_dir.path().join("file");

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    block_on(store.materialize_file(file.clone(), TestData::roland().digest(), false))
      .expect_err("Want unknown digest error");
  }

  #[test]
  fn materialize_file() {
    let materialize_dir = TempDir::new().unwrap();
    let file = materialize_dir.path().join("file");

    let testdata = TestData::roland();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    block_on(store.store_file_bytes(testdata.bytes(), false)).expect("Error saving bytes");
    block_on(store.materialize_file(file.clone(), testdata.digest(), false))
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
    block_on(store.store_file_bytes(testdata.bytes(), false)).expect("Error saving bytes");
    block_on(store.materialize_file(file.clone(), testdata.digest(), true))
      .expect("Error materializing file");
    assert_eq!(file_contents(&file), testdata.bytes());
    assert!(is_executable(&file));
  }

  #[test]
  fn materialize_missing_directory() {
    let materialize_dir = TempDir::new().unwrap();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    block_on(store.materialize_directory(
      materialize_dir.path().to_owned(),
      TestDirectory::recursive().digest(),
    ))
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
    block_on(store.record_directory(&recursive_testdir.directory(), false))
      .expect("Error saving recursive Directory");
    block_on(store.record_directory(&testdir.directory(), false)).expect("Error saving Directory");
    block_on(store.store_file_bytes(roland.bytes(), false)).expect("Error saving file bytes");
    block_on(store.store_file_bytes(catnip.bytes(), false))
      .expect("Error saving catnip file bytes");

    block_on(store.materialize_directory(
      materialize_dir.path().to_owned(),
      recursive_testdir.digest(),
    ))
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
    block_on(store.record_directory(&testdir.directory(), false)).expect("Error saving Directory");
    block_on(store.store_file_bytes(catnip.bytes(), false))
      .expect("Error saving catnip file bytes");

    block_on(store.materialize_directory(materialize_dir.path().to_owned(), testdir.digest()))
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
  fn contents_for_directory_empty() {
    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());

    let file_contents = block_on(store.contents_for_directory(TestDirectory::empty().digest()))
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
    block_on(store.record_directory(&recursive_testdir.directory(), false))
      .expect("Error saving recursive Directory");
    block_on(store.record_directory(&testdir.directory(), false)).expect("Error saving Directory");
    block_on(store.store_file_bytes(roland.bytes(), false)).expect("Error saving file bytes");
    block_on(store.store_file_bytes(catnip.bytes(), false))
      .expect("Error saving catnip file bytes");

    let file_contents = block_on(store.contents_for_directory(recursive_testdir.digest()))
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
      .mode()
      & 0o100
      == 0o100
  }

  pub fn block_on<
    Item: Send + 'static,
    Error: Send + 'static,
    Fut: Future<Item = Item, Error = Error> + Send + 'static,
  >(
    f: Fut,
  ) -> Result<Item, Error> {
    let mut runtime = tokio::runtime::Runtime::new().unwrap();
    runtime.block_on(f)
  }

  #[test]
  fn returns_upload_summary_on_empty_cas() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testroland = TestData::roland();
    let testcatnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland_and_treats();

    let local_store = new_local_store(dir.path());
    block_on(local_store.record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");
    block_on(local_store.store_file_bytes(testroland.bytes(), false))
      .expect("Error storing file locally");
    block_on(local_store.store_file_bytes(testcatnip.bytes(), false))
      .expect("Error storing file locally");
    let mut summary = block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![testdir.digest()]),
    )
    .expect("Error uploading file");

    // We store all 3 files, and so we must sum their digests
    let test_data = vec![
      testdir.digest().1,
      testroland.digest().1,
      testcatnip.digest().1,
    ];
    let test_bytes = test_data.iter().sum();
    summary.upload_wall_time = Duration::default();
    assert_eq!(
      summary,
      UploadSummary {
        ingested_file_count: test_data.len(),
        ingested_file_bytes: test_bytes,
        uploaded_file_count: test_data.len(),
        uploaded_file_bytes: test_bytes,
        upload_wall_time: Duration::default(),
      }
    );
  }

  #[test]
  fn summary_does_not_count_things_in_cas() {
    let dir = TempDir::new().unwrap();
    let cas = StubCAS::empty();

    let testroland = TestData::roland();
    let testcatnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland_and_treats();

    // Store everything locally
    let local_store = new_local_store(dir.path());
    block_on(local_store.record_directory(&testdir.directory(), false))
      .expect("Error storing directory locally");
    block_on(local_store.store_file_bytes(testroland.bytes(), false))
      .expect("Error storing file locally");
    block_on(local_store.store_file_bytes(testcatnip.bytes(), false))
      .expect("Error storing file locally");

    // Store testroland first, which should return a summary of one file
    let mut data_summary = block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![testroland.digest()]),
    )
    .expect("Error uploading file");
    data_summary.upload_wall_time = Duration::default();

    assert_eq!(
      data_summary,
      UploadSummary {
        ingested_file_count: 1,
        ingested_file_bytes: testroland.digest().1,
        uploaded_file_count: 1,
        uploaded_file_bytes: testroland.digest().1,
        upload_wall_time: Duration::default(),
      }
    );

    // Store the directory and catnip.
    // It should see the digest of testroland already in cas,
    // and not report it in uploads.
    let mut dir_summary = block_on(
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(vec![testdir.digest()]),
    )
    .expect("Error uploading directory");

    dir_summary.upload_wall_time = Duration::default();

    assert_eq!(
      dir_summary,
      UploadSummary {
        ingested_file_count: 3,
        ingested_file_bytes: testdir.digest().1 + testroland.digest().1 + testcatnip.digest().1,
        uploaded_file_count: 2,
        uploaded_file_bytes: testdir.digest().1 + testcatnip.digest().1,
        upload_wall_time: Duration::default(),
      }
    );
  }
}
