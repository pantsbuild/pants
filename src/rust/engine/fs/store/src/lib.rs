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
  clippy::unseparated_literal_suffix,
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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
#![type_length_limit = "8576838"]

#[macro_use]
extern crate log;

mod snapshot;
pub use crate::snapshot::{OneOffStoreFileByDigest, Snapshot, StoreFileByDigest};
#[cfg(test)]
mod snapshot_tests;

use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use concrete_time::TimeSpan;
use fs::FileContent;
use futures::compat::Future01CompatExt;
use futures::future::{self as future03, Either, FutureExt, TryFutureExt};
use futures01::{future, Future};
use hashing::Digest;
use protobuf::Message;
use serde_derive::Serialize;
pub use serverset::BackoffConfig;
use std::collections::{BTreeMap, HashMap};
use std::convert::TryInto;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};

use parking_lot::Mutex;

const MEGABYTES: usize = 1024 * 1024;
const GIGABYTES: usize = 1024 * MEGABYTES;

// This is the target number of bytes which should be present in all combined LMDB store files
// after garbage collection. We almost certainly want to make this configurable.
pub const DEFAULT_LOCAL_STORE_GC_TARGET_BYTES: usize = 4 * GIGABYTES;

mod local;
#[cfg(test)]
pub mod local_tests;

mod remote;
#[cfg(test)]
mod remote_tests;

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
  /// Converts this (copy of) a Store to local only by dropping the remote half.
  ///
  /// Because both underlying stores are reference counted, this is cheap, and has no effect on
  /// other clones of the Store.
  ///
  fn into_local_only(self) -> Store {
    Store {
      local: self.local,
      remote: None,
    }
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
  /// Remove a file locally, returning true if it existed, or false otherwise.
  ///
  pub async fn remove_file(&self, digest: Digest) -> Result<bool, String> {
    self.local.remove(EntryType::File, digest).await
  }

  ///
  /// Store a file locally.
  ///
  pub async fn store_file_bytes(
    &self,
    bytes: Bytes,
    initial_lease: bool,
  ) -> Result<Digest, String> {
    self
      .local
      .store_bytes(EntryType::File, bytes, initial_lease)
      .await
  }

  /// Store a digest under a given file path, returning a Snapshot
  pub async fn snapshot_of_one_file(
    &self,
    name: PathBuf,
    digest: hashing::Digest,
    is_executable: bool,
  ) -> Result<Snapshot, String> {
    #[derive(Clone)]
    struct Digester {
      digest: hashing::Digest,
    }

    impl StoreFileByDigest<String> for Digester {
      fn store_by_digest(&self, _: fs::File) -> BoxFuture<hashing::Digest, String> {
        future::ok(self.digest).to_boxed()
      }
    }

    Snapshot::from_path_stats(
      self.clone(),
      Digester { digest },
      vec![fs::PathStat::File {
        path: name.clone(),
        stat: fs::File {
          path: name,
          is_executable: is_executable,
        },
      }],
    )
    .await
  }

  ///
  /// Loads the bytes of the file with the passed fingerprint from the local store and back-fill
  /// from remote when necessary and possible (i.e. when remote is configured), and returns the
  /// result of applying f to that value.
  ///
  pub async fn load_file_bytes_with<
    T: Send + 'static,
    F: Fn(&[u8]) -> T + Send + Sync + 'static,
  >(
    &self,
    digest: Digest,
    f: F,
  ) -> Result<Option<(T, LoadMetadata)>, String> {
    // No transformation or verification is needed for files, so we pass in a pair of functions
    // which always succeed, whether the underlying bytes are coming from a local or remote store.
    // Unfortunately, we need to be a little verbose to do this.
    let f_local = Arc::new(f);
    let f_remote = f_local.clone();
    self
      .load_bytes_with(
        EntryType::File,
        digest,
        move |v: &[u8]| Ok(f_local(v)),
        move |v: Bytes| Ok(f_remote(&v)),
      )
      .await
  }

  ///
  /// Save the bytes of the Directory proto locally, without regard for any of the
  /// contents of any FileNodes or DirectoryNodes therein (i.e. does not require that its
  /// children are already stored).
  ///
  pub async fn record_directory(
    &self,
    directory: &bazel_protos::remote_execution::Directory,
    initial_lease: bool,
  ) -> Result<Digest, String> {
    let local = self.local.clone();
    let bytes = directory
      .write_to_bytes()
      .map_err(|e| format!("Error serializing directory proto {:?}: {:?}", directory, e))?;
    local
      .store_bytes(EntryType::Directory, Bytes::from(bytes), initial_lease)
      .await
  }

  ///
  /// Loads a directory proto from the local store, back-filling from remote if necessary.
  ///
  /// Guarantees that if an Ok Some value is returned, it is valid, and canonical, and its
  /// fingerprint exactly matches that which is requested. Will return an Err if it would return a
  /// non-canonical Directory.
  ///
  pub async fn load_directory(
    &self,
    digest: Digest,
  ) -> Result<Option<(bazel_protos::remote_execution::Directory, LoadMetadata)>, String> {
    self
      .load_bytes_with(
        EntryType::Directory,
        digest,
        // Trust that locally stored values were canonical when they were written into the CAS,
        // don't bother to check this, as it's slightly expensive.
        move |bytes: &[u8]| {
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
      .await
  }

  ///
  /// Loads bytes from remote cas if required and possible (i.e. if remote is configured). Takes
  /// two functions f_local and f_remote. These functions are any validation or transformations you
  /// want to perform on the bytes received from the local and remote cas (if remote is configured).
  ///
  async fn load_bytes_with<
    T: Send + 'static,
    FLocal: Fn(&[u8]) -> Result<T, String> + Send + Sync + 'static,
    FRemote: Fn(Bytes) -> Result<T, String> + Send + Sync + 'static,
  >(
    &self,
    entry_type: EntryType,
    digest: Digest,
    f_local: FLocal,
    f_remote: FRemote,
  ) -> Result<Option<(T, LoadMetadata)>, String> {
    let local = self.local.clone();
    let maybe_remote = self.remote.clone();
    let start = SystemTime::now();
    let maybe_local_value = self
      .local
      .load_bytes_with(entry_type, digest, f_local)
      .await?;

    match (maybe_local_value, maybe_remote) {
      (Some(value_result), _) => value_result.map(|res| Some((res, LoadMetadata::Local))),
      (None, None) => Ok(None),
      (None, Some(remote)) => {
        let maybe_bytes = remote
          .load_bytes_with(entry_type, digest, move |bytes: Bytes| bytes)
          .await?;

        match maybe_bytes {
          Some(bytes) => {
            let value = f_remote(bytes.clone())?;
            let stored_digest = local.store_bytes(entry_type, bytes, true).await?;
            if digest == stored_digest {
              let time_span = TimeSpan::since(&start);
              Ok(Some((value, LoadMetadata::Remote(time_span))))
            } else {
              Err(format!(
                "CAS gave wrong digest: expected {:?}, got {:?}",
                digest, stored_digest
              ))
            }
          }
          None => Ok(None),
        }
      }
    }
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

    let store = self.clone();
    let remote = remote.clone();
    async move {
      let ingested_digests = store.expand_local_digests(digests.iter(), false).await?;
      let digests_to_upload =
        if Store::upload_is_faster_than_checking_whether_to_upload(&ingested_digests) {
          ingested_digests.keys().cloned().collect()
        } else {
          let request = remote.find_missing_blobs_request(ingested_digests.keys());
          remote.list_missing_digests(request).compat().await?
        };

      let uploaded_digests = future03::try_join_all(
        digests_to_upload
          .into_iter()
          .map(|digest| {
            let entry_type = ingested_digests[&digest];
            let local = store.local.clone();
            let remote = remote.clone();

            async move {
              let executor = local.executor().clone();
              let maybe_upload = local
                .load_bytes_with(entry_type, digest, move |bytes| {
                  // NB: `load_bytes_with` runs on a spawned thread which we can safely block.
                  executor.block_on(remote.store_bytes(bytes))
                })
                .await?;
              match maybe_upload {
                Some(res) => res,
                None => Err(format!("Failed to upload digest {:?}: Not found", digest)),
              }
            }
          })
          .collect::<Vec<_>>(),
      )
      .await?;

      let ingested_file_sizes = ingested_digests.iter().map(|(digest, _)| digest.1);
      let uploaded_file_sizes = uploaded_digests.iter().map(|digest| digest.1);

      Ok(UploadSummary {
        ingested_file_count: ingested_file_sizes.len(),
        ingested_file_bytes: ingested_file_sizes.sum(),
        uploaded_file_count: uploaded_file_sizes.len(),
        uploaded_file_bytes: uploaded_file_sizes.sum(),
        upload_wall_time: start_time.elapsed(),
      })
    }
    .boxed()
    .compat()
    .to_boxed()
  }

  ///
  /// Ensure that a directory is locally loadable, which will download it from the Remote store as
  /// a sideeffect (if one is configured). Called only with the Digest of a Directory.
  ///
  pub fn ensure_local_has_recursive_directory(&self, dir_digest: Digest) -> BoxFuture<(), String> {
    let loaded_directory = {
      let store = self.clone();
      let res = async move { store.load_directory(dir_digest).await };
      res.boxed().compat()
    };

    let store = self.clone();
    loaded_directory
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
            let file_digest = try_future!(file_node.get_digest().try_into());
            let store = store.clone();
            Box::pin(async move { store.ensure_local_has_file(file_digest).await })
              .compat()
              .to_boxed()
          })
          .collect::<Vec<_>>();

        // Recursively call with sub-directories
        let directory_futures = directory
          .get_directories()
          .iter()
          .map(move |child_dir| {
            let child_digest = try_future!(child_dir.get_digest().try_into());
            store.ensure_local_has_recursive_directory(child_digest)
          })
          .collect::<Vec<_>>();
        future::join_all(file_futures)
          .join(future::join_all(directory_futures))
          .map(|_| ())
      })
      .to_boxed()
  }

  ///
  /// Ensure that a file is locally loadable, which will download it from the Remote store as
  /// a sideeffect (if one is configured). Called only with the Digest of a File.
  ///
  pub async fn ensure_local_has_file(&self, file_digest: Digest) -> Result<(), String> {
    let result = self
      .load_bytes_with(EntryType::File, file_digest, |_| Ok(()), |_| Ok(()))
      .await?;
    if result.is_some() {
      Ok(())
    } else {
      Err(format!(
        "File {:?} did not exist in the store.",
        file_digest
      ))
    }
  }

  pub async fn lease_all_recursively<'a, Ds: Iterator<Item = &'a Digest>>(
    &self,
    digests: Ds,
  ) -> Result<(), String> {
    let reachable_digests_and_types = self.expand_local_digests(digests, true).await?;
    self
      .local
      .lease_all(reachable_digests_and_types.into_iter())
      .await
  }

  pub fn garbage_collect(
    &self,
    target_size_bytes: usize,
    shrink_behavior: ShrinkBehavior,
  ) -> Result<(), String> {
    match self.local.shrink(target_size_bytes, shrink_behavior) {
      Ok(size) => {
        if size > target_size_bytes {
          log::warn!(
            "Garbage collection attempted to shrink the store to {} bytes but {} bytes \
            are currently in use.",
            target_size_bytes,
            size
          )
        }
        Ok(())
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

  ///
  /// Return all Digests reachable locally from the given root Digests (which may represent either
  /// Files or Directories).
  ///
  /// If `allow_missing`, root digests which do not exist locally will be ignored.
  ///
  pub async fn expand_local_digests<'a, Ds: Iterator<Item = &'a Digest>>(
    &self,
    digests: Ds,
    allow_missing: bool,
  ) -> Result<HashMap<Digest, EntryType>, String> {
    // Expand each digest into either a single file digest, or a collection of recursive digests
    // below a directory.
    let expanded_digests = future03::try_join_all(
      digests
        .map(|digest| {
          let store = self.clone();
          async move {
            match store.local.entry_type(digest.0).await {
              Ok(Some(EntryType::File)) => Ok(Either::Left(*digest)),
              Ok(Some(EntryType::Directory)) => {
                // Locally expand the directory.
                let reachable = store
                  .into_local_only()
                  .expand_directory(*digest)
                  .compat()
                  .await?;
                Ok(Either::Right(reachable))
              }
              Ok(None) => {
                if allow_missing {
                  Ok(Either::Right(HashMap::new()))
                } else {
                  Err(format!("Failed to expand digest {:?}: Not found", digest))
                }
              }
              Err(err) => Err(format!("Failed to expand digest {:?}: {:?}", digest, err)),
            }
          }
        })
        .collect::<Vec<_>>(),
    )
    .await?;

    let mut result: HashMap<Digest, EntryType> = HashMap::new();
    for e in expanded_digests {
      match e {
        Either::Left(digest) => {
          result.insert(digest, EntryType::File);
        }
        Either::Right(reachable_digests) => {
          result.extend(reachable_digests);
        }
      }
    }
    Ok(result)
  }

  pub fn expand_directory(&self, digest: Digest) -> BoxFuture<HashMap<Digest, EntryType>, String> {
    self
      .walk(digest, |_, _, digest, directory| {
        let mut digest_types = Vec::new();
        digest_types.push((digest, EntryType::Directory));
        for file in directory.get_files() {
          digest_types.push((try_future!(file.get_digest().try_into()), EntryType::File));
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
  ) -> BoxFuture<DirectoryMaterializeMetadata, String> {
    let root = Arc::new(Mutex::new(None));
    let executor = self.local.executor().clone();
    self
      .materialize_directory_helper(
        destination.clone(),
        RootOrParentMetadataBuilder::Root(root.clone()),
        digest,
      )
      .and_then(move |()| {
        let materialize_metadata = Arc::try_unwrap(root).unwrap().into_inner().unwrap().build();
        // We fundamentally materialize files for other processes to read; as such, we must ensure
        // data is flushed to disk and visible to them as opposed to just our process. Even though
        // we need to re-open all written files, executing all fsyncs at the end of the
        // materialize call is significantly faster than doing it as we go.
        future::join_all(
          materialize_metadata
            .to_path_list()
            .into_iter()
            .map(|path| {
              let path = destination.join(path);
              executor
                .spawn_blocking(move || {
                  OpenOptions::new()
                    .write(true)
                    .create(false)
                    .open(path)?
                    .sync_all()
                })
                .compat()
            })
            .collect::<Vec<_>>(),
        )
        .map_err(|e| format!("Failed to fsync directory contents: {}", e))
        .map(move |_| materialize_metadata)
      })
      .to_boxed()
  }

  fn materialize_directory_helper(
    &self,
    destination: PathBuf,
    root_or_parent_metadata: RootOrParentMetadataBuilder,
    digest: Digest,
  ) -> BoxFuture<(), String> {
    let store = self.clone();
    async move {
      if let RootOrParentMetadataBuilder::Root(..) = root_or_parent_metadata {
        let destination = destination.clone();
        store
          .local
          .executor()
          .spawn_blocking(move || fs::safe_create_dir_all(&destination))
          .await?;
      } else {
        let destination = destination.clone();
        store
          .local
          .executor()
          .spawn_blocking(move || fs::safe_create_dir(&destination))
          .await?;
      }

      let (directory, metadata) = store
        .load_directory(digest)
        .await?
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

      let file_futures = directory
        .get_files()
        .iter()
        .map(|file_node| {
          let store = store.clone();
          let path = destination.join(file_node.get_name());
          let digest = try_future!(file_node.get_digest().try_into());
          let child_files = child_files.clone();
          let name = file_node.get_name().to_owned();
          store
            .materialize_file(path, digest, file_node.is_executable, false)
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
          let digest = try_future!(directory_node.get_digest().try_into());

          let builder = RootOrParentMetadataBuilder::Parent((
            directory_node.get_name().to_owned(),
            child_directories.clone(),
            child_files.clone(),
          ));

          store.materialize_directory_helper(path, builder, digest)
        })
        .collect::<Vec<_>>();
      let _ = future::join_all(file_futures)
        .join(future::join_all(directory_futures))
        .compat()
        .await?;
      Ok(())
    }
    .boxed()
    .compat()
    .to_boxed()
  }

  ///
  /// Materializes a single file. This method is private because generally files should be
  /// materialized together via `materialize_directory`, which handles batch fsync'ing.
  ///
  fn materialize_file(
    &self,
    destination: PathBuf,
    digest: Digest,
    is_executable: bool,
    fsync: bool,
  ) -> BoxFuture<LoadMetadata, String> {
    let store = self.clone();
    let res = async move {
      let write_result = store
        .load_file_bytes_with(digest, move |bytes| {
          if destination.exists() {
            std::fs::remove_file(&destination)
          } else {
            Ok(())
          }
          .and_then(|_| {
            OpenOptions::new()
              .create(true)
              .write(true)
              .mode(if is_executable { 0o755 } else { 0o644 })
              .open(&destination)
          })
          .and_then(|mut f| {
            f.write_all(&bytes)?;
            if fsync {
              f.sync_all()
            } else {
              Ok(())
            }
          })
          .map_err(|e| format!("Error writing file {:?}: {:?}", destination, e))
        })
        .await?;

      match write_result {
        Some((Ok(()), metadata)) => Ok(metadata),
        Some((Err(e), _metadata)) => Err(e),
        None => Err(format!("File with digest {:?} not found", digest)),
      }
    };
    res.boxed().compat().to_boxed()
  }

  ///
  /// Returns files sorted by their path.
  ///
  pub fn contents_for_directory(&self, digest: Digest) -> BoxFuture<Vec<FileContent>, String> {
    self
      .walk(digest, move |store, path_so_far, _, directory| {
        future::join_all(
          directory
            .get_files()
            .iter()
            .map(|file_node| {
              let path = path_so_far.join(file_node.get_name());
              let is_executable = file_node.is_executable;
              let file_node_digest: Result<_, _> = file_node.get_digest().try_into();
              let store = store.clone();
              let res = async move {
                let maybe_bytes = store
                  .load_file_bytes_with(file_node_digest?, |b| b.into())
                  .await?;
                maybe_bytes
                  .ok_or_else(|| format!("Couldn't find file contents for {:?}", path))
                  .map(|(content, _metadata)| FileContent {
                    path,
                    content,
                    is_executable,
                  })
              };
              res.boxed().compat().to_boxed()
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
    let res = async move {
      let maybe_directory = store.load_directory(digest).await?;
      match maybe_directory {
        Some((directory, _metadata)) => {
          let result_for_directory = f(&store, &path_so_far, digest, &directory).compat().await?;
          {
            let mut accumulator = accumulator.lock();
            accumulator.push(result_for_directory);
          }
          future::join_all(
            directory
              .get_directories()
              .iter()
              .map(move |dir_node| {
                let subdir_digest = try_future!(dir_node.get_digest().try_into());
                let path = path_so_far.join(dir_node.get_name());
                store.walk_helper(subdir_digest, path, f.clone(), accumulator.clone())
              })
              .collect::<Vec<_>>(),
          )
          .compat()
          .await?;
          Ok(())
        }
        None => Err(format!("Could not walk unknown directory: {:?}", digest)),
      }
    };
    res.boxed().compat().to_boxed()
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
mod tests;
