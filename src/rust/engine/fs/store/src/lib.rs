// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

mod snapshot;
pub use crate::snapshot::{OneOffStoreFileByDigest, Snapshot, StoreFileByDigest};

use bazel_protos;
use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use concrete_time::TimeSpan;
use dirs;
use fs::FileContent;
use futures::{future, Future};
use hashing::Digest;
use protobuf::Message;
use serde_derive::Serialize;
pub use serverset::BackoffConfig;
use std::collections::{BTreeMap, HashMap};
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};
use workunit_store::WorkUnitStore;

use parking_lot::Mutex;

const MEGABYTES: usize = 1024 * 1024;
const GIGABYTES: usize = 1024 * MEGABYTES;

// This is the target number of bytes which should be present in all combined LMDB store files
// after garbage collection. We almost certainly want to make this configurable.
pub const DEFAULT_LOCAL_STORE_GC_TARGET_BYTES: usize = 4 * GIGABYTES;

mod local;
mod remote;

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

#[derive(Clone, Debug, PartialEq, Serialize)]
pub enum LoadMetadata {
  Local,
  Remote(TimeSpan),
}

#[derive(Debug, PartialEq, Serialize)]
pub struct DirectoryMaterializeMetadata {
  pub metadata: LoadMetadata,
  pub child_directories: BTreeMap<String, DirectoryMaterializeMetadata>,
  pub child_files: BTreeMap<String, LoadMetadata>,
}

impl DirectoryMaterializeMetadata {
  pub fn to_path_list(&self) -> Vec<String> {
    fn recurse(
      outputs: &mut Vec<String>,
      path_so_far: PathBuf,
      current: &DirectoryMaterializeMetadata,
    ) {
      for (child, _) in current.child_files.iter() {
        outputs.push(path_so_far.join(child).to_string_lossy().to_string())
      }

      for (dir, meta) in current.child_directories.iter() {
        recurse(outputs, path_so_far.join(dir), &meta);
      }
    }
    let mut output_paths: Vec<String> = vec![];
    recurse(&mut output_paths, PathBuf::new(), self);
    output_paths
  }
}

#[derive(Debug)]
struct DirectoryMaterializeMetadataBuilder {
  pub metadata: LoadMetadata,
  pub child_directories: Arc<Mutex<BTreeMap<String, DirectoryMaterializeMetadataBuilder>>>,
  pub child_files: Arc<Mutex<BTreeMap<String, LoadMetadata>>>,
}

impl DirectoryMaterializeMetadataBuilder {
  pub fn new(metadata: LoadMetadata) -> Self {
    DirectoryMaterializeMetadataBuilder {
      metadata,
      child_directories: Arc::new(Mutex::new(BTreeMap::new())),
      child_files: Arc::new(Mutex::new(BTreeMap::new())),
    }
  }
}

impl DirectoryMaterializeMetadataBuilder {
  pub fn build(self) -> DirectoryMaterializeMetadata {
    let child_directories = Arc::try_unwrap(self.child_directories)
      .unwrap()
      .into_inner();
    let child_files = Arc::try_unwrap(self.child_files).unwrap().into_inner();
    DirectoryMaterializeMetadata {
      metadata: self.metadata,
      child_directories: child_directories
        .into_iter()
        .map(|(dir, builder)| (dir, builder.build()))
        .collect(),
      child_files,
    }
  }
}

#[allow(clippy::type_complexity)]
#[derive(Debug)]
enum RootOrParentMetadataBuilder {
  Root(Arc<Mutex<Option<DirectoryMaterializeMetadataBuilder>>>),
  Parent(
    (
      String,
      Arc<Mutex<BTreeMap<String, DirectoryMaterializeMetadataBuilder>>>,
      Arc<Mutex<BTreeMap<String, LoadMetadata>>>,
    ),
  ),
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
  pub fn local_only<P: AsRef<Path>>(
    executor: task_executor::Executor,
    path: P,
  ) -> Result<Store, String> {
    Ok(Store {
      local: local::ByteStore::new(executor, path)?,
      remote: None,
    })
  }

  ///
  /// Make a store which uses local storage, and if it is missing a value which it tries to load,
  /// will attempt to back-fill its local storage from a remote CAS.
  ///
  pub fn with_remote<P: AsRef<Path>>(
    executor: task_executor::Executor,
    path: P,
    cas_addresses: Vec<String>,
    instance_name: Option<String>,
    root_ca_certs: Option<Vec<u8>>,
    oauth_bearer_token: Option<String>,
    thread_count: usize,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
    backoff_config: BackoffConfig,
    rpc_retries: usize,
    connection_limit: usize,
  ) -> Result<Store, String> {
    Ok(Store {
      local: local::ByteStore::new(executor, path)?,
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
        connection_limit,
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

  /// Store a digest under a given file path, returning a Snapshot
  pub fn snapshot_of_one_file(
    &self,
    name: PathBuf,
    digest: hashing::Digest,
    is_executable: bool,
  ) -> BoxFuture<Snapshot, String> {
    let store = self.clone();

    #[derive(Clone)]
    struct Digester {
      digest: hashing::Digest,
    }

    impl StoreFileByDigest<String> for Digester {
      fn store_by_digest(
        &self,
        _: fs::File,
        _: WorkUnitStore,
      ) -> BoxFuture<hashing::Digest, String> {
        future::ok(self.digest).to_boxed()
      }
    }

    Snapshot::from_path_stats(
      store,
      &Digester { digest },
      vec![fs::PathStat::File {
        path: name.clone(),
        stat: fs::File {
          path: name,
          is_executable: is_executable,
        },
      }],
      WorkUnitStore::new(),
    )
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
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Option<(T, LoadMetadata)>, String> {
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
      workunit_store,
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
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Option<(bazel_protos::remote_execution::Directory, LoadMetadata)>, String> {
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
      workunit_store,
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
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Option<(T, LoadMetadata)>, String> {
    let local = self.local.clone();
    let maybe_remote = self.remote.clone();
    let start = SystemTime::now();
    self
      .local
      .load_bytes_with(entry_type, digest, f_local)
      .and_then(
        move |maybe_local_value| match (maybe_local_value, maybe_remote) {
          (Some(value_result), _) => {
            future::done(value_result.map(|res| Some((res, LoadMetadata::Local)))).to_boxed()
          }
          (None, None) => future::ok(None).to_boxed(),
          (None, Some(remote)) => remote
            .load_bytes_with(
              entry_type,
              digest,
              move |bytes: Bytes| bytes,
              workunit_store.clone(),
            )
            .and_then(move |maybe_bytes: Option<Bytes>| match maybe_bytes {
              Some(bytes) => future::done(f_remote(bytes.clone()))
                .and_then(move |value| {
                  local
                    .store_bytes(entry_type, bytes, true)
                    .and_then(move |stored_digest| {
                      if digest == stored_digest {
                        let time_span = TimeSpan::since(&start);
                        Ok(Some((value, LoadMetadata::Remote(time_span))))
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
    workunit_store: WorkUnitStore,
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
          expanding_futures.push(self.expand_directory(digest, workunit_store.clone()));
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
    let workunit_store2 = workunit_store.clone();
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
        let f = remote.list_missing_digests(request, workunit_store.clone());
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
              let workunit_store = workunit_store2.clone();
              local
                .load_bytes_with(entry_type, digest, move |bytes| {
                  remote.store_bytes(bytes, workunit_store.clone())
                })
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
  pub fn ensure_local_has_recursive_directory(
    &self,
    dir_digest: Digest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<(), String> {
    let store = self.clone();
    self
      .load_directory(dir_digest, workunit_store.clone())
      .and_then(move |directory_opt| {
        directory_opt
          .map(|(dir, _metadata)| dir)
          .ok_or_else(|| format!("Could not read dir with digest {:?}", dir_digest))
      })
      .and_then(move |directory| {
        // Traverse the files within directory
        let file_futures = directory
          .get_files()
          .iter()
          .map(|file_node| {
            let file_digest = try_future!(file_node.get_digest().into());
            store.load_bytes_with(
              EntryType::File,
              file_digest,
              |_| Ok(()),
              |_| Ok(()),
              workunit_store.clone(),
            )
          })
          .collect::<Vec<_>>();

        // Recursively call with sub-directories
        let directory_futures = directory
          .get_directories()
          .iter()
          .map(move |child_dir| {
            let child_digest = try_future!(child_dir.get_digest().into());
            store.ensure_local_has_recursive_directory(child_digest, workunit_store.clone())
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

  pub fn expand_directory(
    &self,
    digest: Digest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<HashMap<Digest, EntryType>, String> {
    self
      .walk(
        digest,
        |_, _, digest, directory| {
          let mut digest_types = Vec::new();
          digest_types.push((digest, EntryType::Directory));
          for file in directory.get_files() {
            digest_types.push((try_future!(file.get_digest().into()), EntryType::File));
          }
          future::ok(digest_types).to_boxed()
        },
        workunit_store,
      )
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
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<DirectoryMaterializeMetadata, String> {
    let root = Arc::new(Mutex::new(None));
    self
      .materialize_directory_helper(
        destination,
        RootOrParentMetadataBuilder::Root(root.clone()),
        digest,
        workunit_store,
      )
      .map(|()| Arc::try_unwrap(root).unwrap().into_inner().unwrap().build())
      .to_boxed()
  }

  fn materialize_directory_helper(
    &self,
    destination: PathBuf,
    root_or_parent_metadata: RootOrParentMetadataBuilder,
    digest: Digest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<(), String> {
    if let RootOrParentMetadataBuilder::Root(..) = root_or_parent_metadata {
      try_future!(fs::safe_create_dir_all(&destination));
    } else {
      try_future!(fs::safe_create_dir(&destination));
    }

    let store = self.clone();
    self
      .load_directory(digest, workunit_store.clone())
      .and_then(move |directory_and_metadata_opt| {
        let (directory, metadata) = directory_and_metadata_opt
          .ok_or_else(|| format!("Directory with digest {:?} not found", digest))?;
        let (child_directories, child_files) = match root_or_parent_metadata {
          RootOrParentMetadataBuilder::Root(root) => {
            let builder = DirectoryMaterializeMetadataBuilder::new(metadata);
            let child_directories = builder.child_directories.clone();
            let child_files = builder.child_files.clone();
            *root.lock() = Some(builder);
            (child_directories, child_files)
          }
          RootOrParentMetadataBuilder::Parent((
            dir_name,
            parent_child_directories,
            _parent_files,
          )) => {
            let builder = DirectoryMaterializeMetadataBuilder::new(metadata);
            let child_directories = builder.child_directories.clone();
            let child_files = builder.child_files.clone();
            parent_child_directories.lock().insert(dir_name, builder);
            (child_directories, child_files)
          }
        };
        Ok((directory, child_directories, child_files))
      })
      .and_then(move |(directory, child_directories, child_files)| {
        let file_futures = directory
          .get_files()
          .iter()
          .map(|file_node| {
            let store = store.clone();
            let path = destination.join(file_node.get_name());
            let digest = try_future!(file_node.get_digest().into());
            let child_files = child_files.clone();
            let name = file_node.get_name().to_owned();
            store
              .materialize_file(
                path,
                digest,
                file_node.is_executable,
                workunit_store.clone(),
              )
              .map(move |metadata| child_files.lock().insert(name, metadata))
              .to_boxed()
          })
          .collect::<Vec<_>>();
        let directory_futures = directory
          .get_directories()
          .iter()
          .map(|directory_node| {
            let store = store.clone();
            let path = destination.join(directory_node.get_name());
            let digest = try_future!(directory_node.get_digest().into());

            let builder = RootOrParentMetadataBuilder::Parent((
              directory_node.get_name().to_owned(),
              child_directories.clone(),
              child_files.clone(),
            ));

            store.materialize_directory_helper(path, builder, digest, workunit_store.clone())
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
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<LoadMetadata, String> {
    self
      .load_file_bytes_with(
        digest,
        move |bytes| {
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
        },
        workunit_store.clone(),
      )
      .and_then(move |write_result| match write_result {
        Some((Ok(()), metadata)) => Ok(metadata),
        Some((Err(e), _metadata)) => Err(e),
        None => Err(format!("File with digest {:?} not found", digest)),
      })
      .to_boxed()
  }

  // Returns files sorted by their path.
  pub fn contents_for_directory(
    &self,
    digest: Digest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Vec<FileContent>, String> {
    let workunit_store_clone = workunit_store.clone();
    self
      .walk(
        digest,
        move |store, path_so_far, _, directory| {
          future::join_all(
            directory
              .get_files()
              .iter()
              .map(|file_node| {
                let path = path_so_far.join(file_node.get_name());
                let is_executable = file_node.is_executable;
                store
                  .load_file_bytes_with(
                    try_future!(file_node.get_digest().into()),
                    |b| b,
                    workunit_store.clone(),
                  )
                  .and_then(move |maybe_bytes| {
                    maybe_bytes
                      .ok_or_else(|| format!("Couldn't find file contents for {:?}", path))
                      .map(|(content, _metadata)| FileContent {
                        path,
                        content,
                        is_executable,
                      })
                  })
                  .to_boxed()
              })
              .collect::<Vec<_>>(),
          )
          .to_boxed()
        },
        workunit_store_clone,
      )
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
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Vec<T>, String> {
    let f = Arc::new(f);
    let accumulator = Arc::new(Mutex::new(Vec::new()));
    self
      .walk_helper(
        digest,
        PathBuf::new(),
        f,
        accumulator.clone(),
        workunit_store,
      )
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
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<(), String> {
    let store = self.clone();
    self
      .load_directory(digest, workunit_store.clone())
      .and_then(move |maybe_directory| match maybe_directory {
        Some((directory, _metadata)) => {
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
                    store.walk_helper(
                      subdir_digest,
                      path,
                      f.clone(),
                      accumulator.clone(),
                      workunit_store.clone(),
                    )
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

  pub fn all_local_digests(&self, entry_type: EntryType) -> Result<Vec<Digest>, String> {
    self.local.all_digests(entry_type)
  }
}

// Only public for testing.
#[derive(Copy, Clone, Debug, Eq, Hash, PartialEq, Ord, PartialOrd)]
pub enum EntryType {
  Directory,
  File,
}

#[cfg(test)]
mod tests {
  use super::{
    local, DirectoryMaterializeMetadata, EntryType, FileContent, LoadMetadata, Store,
    UploadSummary, MEGABYTES,
  };

  use bazel_protos;
  use bytes::Bytes;
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::Future;
  use hashing::{Digest, Fingerprint};
  use maplit::btreemap;
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
  use workunit_store::WorkUnitStore;

  impl LoadMetadata {
    fn is_remote(&self) -> bool {
      match self {
        LoadMetadata::Local => false,
        LoadMetadata::Remote(_) => true,
      }
    }
  }

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
    block_on(store.load_file_bytes_with(digest, |bytes| bytes, WorkUnitStore::new()))
      .map(|option| option.map(|(bytes, _metadata)| bytes))
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
    Store::local_only(task_executor::Executor::new(), dir).expect("Error creating local store")
  }

  ///
  /// Create a new store with a remote CAS.
  ///
  fn new_store<P: AsRef<Path>>(dir: P, cas_address: String) -> Store {
    Store::with_remote(
      task_executor::Executor::new(),
      dir,
      vec![cas_address],
      None,
      None,
      None,
      1,
      10 * MEGABYTES,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      1,
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
      load_file_bytes(&new_store(dir.path(), cas.address()), testdata.digest(),),
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
      block_on(
        new_store(dir.path(), cas.address()).load_directory(testdir.digest(), WorkUnitStore::new())
      )
      .unwrap()
      .unwrap()
      .0,
      testdir.directory()
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
      local::tests::load_file_bytes(&local::tests::new_store(dir.path()), testdata.digest(),),
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
      block_on(
        new_store(dir.path(), cas.address()).load_directory(testdir.digest(), WorkUnitStore::new())
      )
      .unwrap()
      .unwrap()
      .0,
      testdir.directory()
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
        .ensure_local_has_recursive_directory(recursive_testdir_digest, WorkUnitStore::new()),
    )
    .expect("Downloading recursive directory should have succeeded.");

    assert_eq!(
      load_file_bytes(&new_local_store(dir.path()), roland.digest(),),
      Ok(Some(roland.bytes()))
    );
    assert_eq!(
      load_file_bytes(&new_local_store(dir.path()), catnip.digest(),),
      Ok(Some(catnip.bytes()))
    );
    assert_eq!(
      block_on(new_local_store(dir.path()).load_directory(testdir_digest, WorkUnitStore::new()))
        .unwrap()
        .unwrap()
        .0,
      testdir_directory
    );
    assert_eq!(
      block_on(
        new_local_store(dir.path()).load_directory(recursive_testdir_digest, WorkUnitStore::new())
      )
      .unwrap()
      .unwrap()
      .0,
      recursive_testdir_directory
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
      block_on(new_store(dir.path(), cas.address()).load_directory(
        TestDirectory::containing_roland().digest(),
        WorkUnitStore::new()
      )),
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
    let error = block_on(
      new_store(dir.path(), cas.address())
        .load_directory(TestData::roland().digest(), WorkUnitStore::new()),
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
  fn malformed_remote_directory_is_error() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let cas = new_cas(1024);
    block_on(
      new_store(dir.path(), cas.address()).load_directory(testdata.digest(), WorkUnitStore::new()),
    )
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
    block_on(
      new_store(dir.path(), cas.address())
        .load_directory(directory_digest.clone(), WorkUnitStore::new()),
    )
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

    let expanded = block_on(
      new_local_store(dir.path()).expand_directory(empty_dir.digest(), WorkUnitStore::new()),
    )
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

    let expanded = block_on(
      new_local_store(dir.path()).expand_directory(testdir.digest(), WorkUnitStore::new()),
    )
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

    let expanded = block_on(
      new_local_store(dir.path())
        .expand_directory(recursive_testdir.digest(), WorkUnitStore::new()),
    )
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
      block_on(new_local_store(dir.path()).expand_directory(digest, WorkUnitStore::new()))
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

    block_on(new_local_store(dir.path()).record_directory(&recursive_testdir.directory(), false))
      .expect("Error storing directory locally");

    let error = block_on(
      new_local_store(dir.path())
        .expand_directory(recursive_testdir.digest(), WorkUnitStore::new()),
    )
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
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testdata.digest()], WorkUnitStore::new()),
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
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testdir.digest()], WorkUnitStore::new()),
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
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testdata.digest()], WorkUnitStore::new()),
    )
    .expect("Error uploading file");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
      cas.blobs.lock().get(&testdata.fingerprint()),
      Some(&testdata.bytes())
    );
    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

    block_on(
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testdir.digest()], WorkUnitStore::new()),
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
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![roland.digest()], WorkUnitStore::new()),
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
      new_store(dir.path(), cas.address()).ensure_remote_has_recursive(
        vec![testdir.digest(), catnip.digest()],
        WorkUnitStore::new(),
      ),
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
        .ensure_remote_has_recursive(vec![extra_big_file_digest()], WorkUnitStore::new()),
    )
    .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
      cas.blobs.lock().get(&extra_big_file_fingerprint()),
      Some(&extra_big_file_bytes())
    );

    block_on(
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![extra_big_file_digest()], WorkUnitStore::new()),
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
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testdata.digest()], WorkUnitStore::new()),
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
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testdir.digest()], WorkUnitStore::new()),
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

    block_on(
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![wrong_digest], WorkUnitStore::new()),
    )
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
      task_executor::Executor::new(),
      dir.path(),
      vec![cas.address()],
      Some("dark-tower".to_owned()),
      None,
      None,
      1,
      10 * MEGABYTES,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      1,
    )
    .unwrap();

    block_on(
      store_with_remote.ensure_remote_has_recursive(vec![testdir.digest()], WorkUnitStore::new()),
    )
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
      task_executor::Executor::new(),
      dir.path(),
      vec![cas.address()],
      Some("dark-tower".to_owned()),
      None,
      None,
      1,
      10 * MEGABYTES,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      1,
    )
    .unwrap();

    assert_eq!(
      block_on(store_with_remote.load_file_bytes_with(
        TestData::roland().digest(),
        |b| b,
        WorkUnitStore::new()
      ))
      .unwrap()
      .unwrap()
      .0,
      TestData::roland().bytes()
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
      task_executor::Executor::new(),
      dir.path(),
      vec![cas.address()],
      None,
      None,
      Some("Armory.Key".to_owned()),
      1,
      10 * MEGABYTES,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      1,
    )
    .unwrap();

    block_on(
      store_with_remote.ensure_remote_has_recursive(vec![testdir.digest()], WorkUnitStore::new()),
    )
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
      task_executor::Executor::new(),
      dir.path(),
      vec![cas.address()],
      None,
      None,
      Some("Armory.Key".to_owned()),
      1,
      10 * MEGABYTES,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      1,
    )
    .unwrap();

    assert_eq!(
      block_on(store_with_remote.load_file_bytes_with(
        TestData::roland().digest(),
        |b| b,
        WorkUnitStore::new()
      ))
      .unwrap()
      .unwrap()
      .0,
      TestData::roland().bytes()
    )
  }

  #[test]
  fn materialize_missing_file() {
    let materialize_dir = TempDir::new().unwrap();
    let file = materialize_dir.path().join("file");

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    block_on(store.materialize_file(
      file.clone(),
      TestData::roland().digest(),
      false,
      WorkUnitStore::new(),
    ))
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
    block_on(store.materialize_file(file.clone(), testdata.digest(), false, WorkUnitStore::new()))
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
    block_on(store.materialize_file(file.clone(), testdata.digest(), true, WorkUnitStore::new()))
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
      WorkUnitStore::new(),
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
      WorkUnitStore::new(),
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

    block_on(store.materialize_directory(
      materialize_dir.path().to_owned(),
      testdir.digest(),
      WorkUnitStore::new(),
    ))
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

    let file_contents =
      block_on(store.contents_for_directory(TestDirectory::empty().digest(), WorkUnitStore::new()))
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

    let file_contents =
      block_on(store.contents_for_directory(recursive_testdir.digest(), WorkUnitStore::new()))
        .expect("Getting FileContents");

    assert_same_filecontents(
      file_contents,
      vec![
        FileContent {
          path: PathBuf::from("cats").join("roland"),
          content: roland.bytes(),
          is_executable: false,
        },
        FileContent {
          path: PathBuf::from("treats"),
          content: catnip.bytes(),
          is_executable: false,
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
      if l.is_executable != r.is_executable {
        success = false;
        eprintln!(
          "Executable bit did not match for index {}: {:?}, {:?}",
          index, l.is_executable, r.is_executable
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
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testdir.digest()], WorkUnitStore::new()),
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
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testroland.digest()], WorkUnitStore::new()),
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
      new_store(dir.path(), cas.address())
        .ensure_remote_has_recursive(vec![testdir.digest()], WorkUnitStore::new()),
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

  #[test]
  fn materialize_directory_metadata_all_local() {
    let outer_dir = TestDirectory::double_nested();
    let nested_dir = TestDirectory::nested();
    let inner_dir = TestDirectory::containing_roland();
    let file = TestData::roland();

    let mut runtime = tokio::runtime::Runtime::new().unwrap();

    let dir = tempfile::tempdir().unwrap();
    let store = new_local_store(dir.path());
    runtime
      .block_on(store.record_directory(&outer_dir.directory(), false))
      .expect("Error storing directory locally");
    runtime
      .block_on(store.record_directory(&nested_dir.directory(), false))
      .expect("Error storing directory locally");
    runtime
      .block_on(store.record_directory(&inner_dir.directory(), false))
      .expect("Error storing directory locally");
    runtime
      .block_on(store.store_file_bytes(file.bytes(), false))
      .expect("Error storing file locally");

    let mat_dir = tempfile::tempdir().unwrap();
    let metadata = runtime
      .block_on(store.materialize_directory(
        mat_dir.path().to_owned(),
        outer_dir.digest(),
        WorkUnitStore::new(),
      ))
      .unwrap();

    let local = LoadMetadata::Local;

    let want = DirectoryMaterializeMetadata {
      metadata: local.clone(),
      child_directories: btreemap! {
        "pets".to_owned() => DirectoryMaterializeMetadata {
          metadata: local.clone(),
          child_directories: btreemap!{
            "cats".to_owned() => DirectoryMaterializeMetadata {
              metadata: local.clone(),
              child_directories: btreemap!{},
              child_files: btreemap!{
                "roland".to_owned() => local.clone(),
              },
            }
          },
          child_files: btreemap!{},
        }
      },
      child_files: btreemap! {},
    };

    assert_eq!(want, metadata);
  }

  #[test]
  fn materialize_directory_metadata_mixed() {
    let outer_dir = TestDirectory::double_nested();
    let nested_dir = TestDirectory::nested();
    let inner_dir = TestDirectory::containing_roland();
    let file = TestData::roland();

    let cas = StubCAS::builder().directory(&nested_dir).build();
    let mut runtime = tokio::runtime::Runtime::new().unwrap();

    let dir = tempfile::tempdir().unwrap();
    let store = new_store(dir.path(), cas.address());
    runtime
      .block_on(store.record_directory(&outer_dir.directory(), false))
      .expect("Error storing directory locally");
    runtime
      .block_on(store.record_directory(&inner_dir.directory(), false))
      .expect("Error storing directory locally");
    runtime
      .block_on(store.store_file_bytes(file.bytes(), false))
      .expect("Error storing file locally");

    let mat_dir = tempfile::tempdir().unwrap();
    let metadata = runtime
      .block_on(store.materialize_directory(
        mat_dir.path().to_owned(),
        outer_dir.digest(),
        WorkUnitStore::new(),
      ))
      .unwrap();

    assert!(metadata
      .child_directories
      .get("pets")
      .unwrap()
      .metadata
      .is_remote());
    assert_eq!(
      LoadMetadata::Local,
      *metadata
        .child_directories
        .get("pets")
        .unwrap()
        .child_directories
        .get("cats")
        .unwrap()
        .child_files
        .get("roland")
        .unwrap()
    );
  }
}
