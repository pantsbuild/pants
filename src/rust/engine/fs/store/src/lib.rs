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
#![recursion_limit = "256"]

mod immutable_inputs;
pub use crate::immutable_inputs::{ImmutableInputs, WorkdirSymlink};
mod snapshot;
pub use crate::snapshot::{OneOffStoreFileByDigest, Snapshot, StoreFileByDigest};
mod snapshot_ops;
#[cfg(test)]
mod snapshot_ops_tests;
#[cfg(test)]
mod snapshot_tests;
pub use crate::snapshot_ops::{SnapshotOps, SubsetParams};

use std::collections::{BTreeSet, HashMap, HashSet};
use std::fmt::{self, Debug, Display};
use std::fs::OpenOptions;
use std::fs::Permissions as FSPermissions;
use std::future::Future;
use std::io::Write;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Weak};
use std::time::{Duration, Instant};

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bytes::Bytes;
use fs::{
  default_cache_path, directory, DigestEntry, DigestTrie, Dir, DirectoryDigest, File, FileContent,
  FileEntry, Link, PathStat, Permissions, RelativePath, SymlinkBehavior, SymlinkEntry,
  EMPTY_DIRECTORY_DIGEST,
};
use futures::future::{self, BoxFuture, Either, FutureExt, TryFutureExt};
use grpc_util::prost::MessageExt;
use hashing::{Digest, Fingerprint};
use local::ByteStore;
use parking_lot::Mutex;
use prost::Message;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::require_digest;
use remexec::Tree;
use serde_derive::Serialize;
use sharded_lmdb::DEFAULT_LEASE_TIME;
#[cfg(target_os = "macos")]
use tokio::fs::copy;
#[cfg(not(target_os = "macos"))]
use tokio::fs::hard_link;
use tokio::fs::symlink;
use tryfuture::try_future;
use workunit_store::{in_workunit, Level, Metric};

const KILOBYTES: usize = 1024;
const MEGABYTES: usize = 1024 * KILOBYTES;
const GIGABYTES: usize = 1024 * MEGABYTES;

mod local;
#[cfg(test)]
pub mod local_tests;

pub mod remote;
#[cfg(test)]
mod remote_tests;

// Consumers of this crate shouldn't need to worry about the exact crate structure that comes
// together to make a store.
pub use remote_provider_traits::RemoteOptions;

pub struct LocalOptions {
  pub files_max_size_bytes: usize,
  pub directories_max_size_bytes: usize,
  pub lease_time: Duration,
  pub shard_count: u8,
}

///
/// NB: These defaults are intended primarily for use in tests: high level code should expose
/// explicit settings in most cases.
///
impl Default for LocalOptions {
  fn default() -> Self {
    Self {
      files_max_size_bytes: 16 * 4 * GIGABYTES,
      directories_max_size_bytes: 2 * 4 * GIGABYTES,
      lease_time: DEFAULT_LEASE_TIME,
      shard_count: 16,
    }
  }
}

#[derive(Debug, PartialEq, Eq)]
pub enum StoreError {
  /// A Digest was not present in either of the local or remote Stores.
  MissingDigest(String, Digest),
  /// All other error types.
  Unclassified(String),
}

impl StoreError {
  pub fn enrich(self, prefix: &str) -> Self {
    match self {
      Self::MissingDigest(s, d) => Self::MissingDigest(format!("{prefix}: {s}"), d),
      Self::Unclassified(s) => Self::Unclassified(format!("{prefix}: {s}")),
    }
  }
}

impl Display for StoreError {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    match self {
      Self::MissingDigest(s, d) => {
        write!(f, "{s}: {d:?}")
      }
      Self::Unclassified(s) => write!(f, "{s}"),
    }
  }
}

impl From<String> for StoreError {
  fn from(err: String) -> Self {
    Self::Unclassified(err)
  }
}

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
/// Wraps a `remote::ByteStore` with state to help avoid uploading common blobs multiple times.
///
/// If a blob is generated that many downstream actions depend on, we would otherwise get an
/// expanded set of digests from each of those actions that includes the new blob. If those actions
/// all execute in a time window smaller than the time taken to upload the blob, the effort would be
/// duplicated leading to both wasted resources locally buffering up the blob as well as wasted
/// effort on the remote server depending on its handling of this.
///
#[derive(Clone, Debug)]
struct RemoteStore {
  store: remote::ByteStore,
  in_flight_uploads: Arc<Mutex<HashMap<Digest, Weak<OnceCell<()>>>>>,
  in_flight_downloads: Arc<Mutex<HashMap<Digest, Weak<OnceCell<()>>>>>,
}

impl RemoteStore {
  fn new(store: remote::ByteStore) -> Self {
    Self {
      store,
      in_flight_uploads: Arc::default(),
      in_flight_downloads: Arc::default(),
    }
  }

  ///
  /// Returns a strongly held cell from a map of weakly held cells, creating it if necessary.
  ///
  fn cell_from(
    cells: &Mutex<HashMap<Digest, Weak<OnceCell<()>>>>,
    digest: Digest,
  ) -> Arc<OnceCell<()>> {
    let mut cells = cells.lock();
    if let Some(cell) = cells.get(&digest).and_then(|weak_cell| weak_cell.upgrade()) {
      cell
    } else {
      let cell = Arc::new(OnceCell::new());
      cells.insert(digest, Arc::downgrade(&cell));
      cell
    }
  }

  ///
  /// Guards an attempt to upload the given `Digest`, skipping the upload if another attempt has
  /// been successful. Will not return until either an attempt has succeed, or this attempt has
  /// failed.
  ///
  async fn maybe_upload<E>(
    &self,
    digest: Digest,
    upload: impl Future<Output = Result<(), E>>,
  ) -> Result<(), E> {
    Self::cell_from(&self.in_flight_uploads, digest)
      .get_or_try_init(upload)
      .await
      .map(|&()| ())
  }

  ///
  /// Guards an attempt to download the given `Digest`, skipping the download if another attempt
  /// has been successful. Will not return until either an attempt has succeed, or this attempt has
  /// failed.
  ///
  async fn maybe_download<E>(
    &self,
    digest: Digest,
    upload: impl Future<Output = Result<(), E>>,
  ) -> Result<(), E> {
    Self::cell_from(&self.in_flight_downloads, digest)
      .get_or_try_init(upload)
      .await
      .map(|&()| ())
  }

  async fn remote_writer(
    remote_store: &remote::ByteStore,
    digest: Digest,
    file: tokio::fs::File,
  ) -> Result<tokio::fs::File, StoreError> {
    remote_store.load_file(digest, file).await?.ok_or_else(|| {
      StoreError::MissingDigest(
        "Was not present in either the local or remote store".to_owned(),
        digest,
      )
    })
  }

  /// Download the digest to the local byte store from this remote store. The function `f_remote`
  /// can be used to validate the bytes (NB. if provided, the whole value will be buffered into
  /// memory to provide the `Bytes` argument, and thus `f_remote` should only be used for small digests).
  async fn download_digest_to_local(
    &self,
    local_store: local::ByteStore,
    digest: Digest,
    entry_type: EntryType,
    f_remote: Option<&(dyn Fn(Bytes) -> Result<(), String> + Send + Sync + 'static)>,
  ) -> Result<(), StoreError> {
    let remote_store = self.store.clone();
    self
      .maybe_download(digest, async move {
        let store_into_fsdb = ByteStore::should_use_fsdb(entry_type, digest.size_bytes);
        if store_into_fsdb {
          assert!(
            f_remote.is_none(),
            "Entries to be stored in FSDB should never need validation via f_remote, found {digest:?} of type {entry_type:?} that does"
          );
          local_store
            .get_file_fsdb()
            .write_using(digest.hash, |file| {
              Self::remote_writer(&remote_store, digest, file)
            })
            .await?;
        } else {
          let bytes = remote_store.load_bytes(digest).await?.ok_or_else(|| {
            StoreError::MissingDigest(
              "Was not present in either the local or remote store".to_owned(),
              digest,
            )
          })?;
          if let Some(f_remote) = f_remote {
            f_remote(bytes.clone())?;
          }
          local_store
            .store_bytes(entry_type, digest.hash, bytes, true)
            .await?;
        }
        Ok(())
      })
      .await
  }
}

///
/// A content-addressed store of file contents, and Directories.
///
/// Store keeps content on disk, and can optionally delegate to backfill its on-disk storage by
/// fetching files from a remote server which implements the gRPC bytestream interface
/// (see <https://github.com/googleapis/googleapis/blob/master/google/bytestream/bytestream.proto>)
/// as specified by the gRPC remote execution interface (see
/// <https://github.com/googleapis/googleapis/blob/master/google/devtools/remoteexecution/v1test/>)
///
/// It can also write back to a remote gRPC server, but will only do so when explicitly instructed
/// to do so.
///
#[derive(Debug, Clone)]
pub struct Store {
  local: local::ByteStore,
  remote: Option<RemoteStore>,
  immutable_inputs_base: Option<PathBuf>,
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
// We may want to re-visit this if we end up wanting to handle local/remote/merged interchangeably.
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
      immutable_inputs_base: None,
    })
  }

  pub fn local_only_with_options<P: AsRef<Path>>(
    executor: task_executor::Executor,
    path: P,
    immutable_inputs_base: &Path,
    options: LocalOptions,
  ) -> Result<Store, String> {
    Ok(Store {
      local: local::ByteStore::new_with_options(executor, path, options)?,
      remote: None,
      immutable_inputs_base: Some(immutable_inputs_base.to_path_buf()),
    })
  }

  ///
  /// Converts this (copy of) a Store to local only by dropping the remote half.
  ///
  /// Because both underlying stores are reference counted, this is cheap, and has no effect on
  /// other clones of the Store.
  ///
  pub fn into_local_only(self) -> Store {
    Store {
      local: self.local,
      remote: None,
      immutable_inputs_base: self.immutable_inputs_base,
    }
  }

  ///
  /// Add remote storage to a Store. If it is missing a value which it tries to load, it will
  /// attempt to back-fill its local storage from the remote storage.
  ///
  pub async fn into_with_remote(self, remote_options: RemoteOptions) -> Result<Store, String> {
    Ok(Store {
      local: self.local,
      remote: Some(RemoteStore::new(
        remote::ByteStore::from_options(remote_options).await?,
      )),
      immutable_inputs_base: self.immutable_inputs_base,
    })
  }

  // This default suffix is also hard-coded into the Python options code in global_options.py
  pub fn default_path() -> PathBuf {
    default_cache_path().join("lmdb_store")
  }

  ///
  /// Remove a file locally, returning true if it existed, or false otherwise.
  ///
  pub async fn remove_file(&self, digest: Digest) -> Result<bool, String> {
    self.local.remove(EntryType::File, digest).await
  }

  ///
  /// A convenience method for storing small files.
  ///
  /// NB: This method should not be used for large blobs: prefer to stream them from their source
  /// using `store_file`.
  ///
  pub async fn store_file_bytes(
    &self,
    bytes: Bytes,
    initial_lease: bool,
  ) -> Result<Digest, String> {
    let digest = Digest::of_bytes(&bytes);
    self
      .local
      .store_bytes(EntryType::File, digest.hash, bytes, initial_lease)
      .await?;
    Ok(digest)
  }

  ///
  /// A convenience method for storing batches of small files.
  ///
  /// NB: This method should not be used for large blobs: prefer to stream them from their source
  /// using `store_file`.
  ///
  pub async fn store_file_bytes_batch(
    &self,
    items: Vec<(Fingerprint, Bytes)>,
    initial_lease: bool,
  ) -> Result<(), String> {
    self
      .local
      .store_bytes_batch(EntryType::File, items, initial_lease)
      .await?;
    Ok(())
  }

  ///
  /// Store a file locally by streaming its contents.
  ///
  pub async fn store_file(
    &self,
    initial_lease: bool,
    data_is_immutable: bool,
    src: PathBuf,
  ) -> Result<Digest, String> {
    self
      .local
      .store(EntryType::File, initial_lease, data_is_immutable, src)
      .await
  }

  /// Store a digest under a given file path, returning a Snapshot
  pub async fn snapshot_of_one_file(
    &self,
    name: RelativePath,
    digest: hashing::Digest,
    is_executable: bool,
  ) -> Result<Snapshot, String> {
    #[derive(Clone)]
    struct Digester {
      digest: hashing::Digest,
    }

    impl StoreFileByDigest<String> for Digester {
      fn store_by_digest(
        &self,
        _: fs::File,
      ) -> future::BoxFuture<'static, Result<hashing::Digest, String>> {
        future::ok(self.digest).boxed()
      }
    }

    Snapshot::from_path_stats(
      Digester { digest },
      vec![fs::PathStat::File {
        path: name.clone().into(),
        stat: fs::File {
          path: name.into(),
          is_executable,
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
    F: Fn(&[u8]) -> T + Clone + Send + Sync + 'static,
  >(
    &self,
    digest: Digest,
    f: F,
  ) -> Result<T, StoreError> {
    // No transformation or verification (beyond verifying their digest, which the
    // `remote::ByteStore` will do) is needed for files.
    self
      .load_bytes_with(EntryType::File, digest, move |v: &[u8]| Ok(f(v)), None)
      .await
  }

  ///
  /// Ensure that the recursive contents of the given DigestTrie are persisted in the local Store.
  ///
  pub async fn record_digest_trie(
    &self,
    tree: DigestTrie,
    initial_lease: bool,
  ) -> Result<DirectoryDigest, String> {
    // Collect all Directory structs in the trie.
    let mut directories = Vec::new();
    tree.walk(SymlinkBehavior::Aware, &mut |_, entry| match entry {
      directory::Entry::Directory(d) => {
        let directory = d.as_remexec_directory();
        if cfg!(debug_assertions) {
          protos::verify_directory_canonical(d.digest(), &directory).unwrap();
        }
        directories.push((d.digest().hash, directory.to_bytes()))
      }
      directory::Entry::File(_) => (),
      directory::Entry::Symlink(_) => (),
    });

    // Then store them as a batch.
    let local = self.local.clone();
    let root = &directories[0];
    let top_digest = Digest::new(root.0, root.1.len());
    local
      .store_bytes_batch(EntryType::Directory, directories, initial_lease)
      .await?;

    Ok(DirectoryDigest::new(top_digest, tree))
  }

  ///
  /// Save the bytes of the Directory proto locally, without regard for any of the
  /// contents of any FileNodes or DirectoryNodes therein (i.e. does not require that its
  /// children are already stored).
  ///
  pub async fn record_directory(
    &self,
    directory: &remexec::Directory,
    initial_lease: bool,
  ) -> Result<Digest, String> {
    let local = self.local.clone();
    let bytes = directory.to_bytes();
    let digest = Digest::of_bytes(&bytes);
    local
      .store_bytes(
        EntryType::Directory,
        digest.hash,
        directory.to_bytes(),
        initial_lease,
      )
      .await?;
    if cfg!(debug_assertions) {
      protos::verify_directory_canonical(digest, directory)?;
    }
    Ok(digest)
  }

  ///
  /// Loads a DigestTree from the local store, back-filling from remote if necessary.
  ///
  /// TODO: Add a native implementation that skips creating PathStats and directly produces
  /// a DigestTrie.
  ///
  pub async fn load_digest_trie(&self, digest: DirectoryDigest) -> Result<DigestTrie, StoreError> {
    if let Some(tree) = digest.tree {
      // The DigestTrie is already loaded.
      return Ok(tree);
    }

    // The DigestTrie needs to be loaded from the Store.
    let path_stats_per_directory = self
      .walk(digest.as_digest(), |_, path_so_far, _, directory| {
        let mut path_stats = Vec::new();
        path_stats.extend(directory.directories.iter().map(move |dir_node| {
          let path = path_so_far.join(&dir_node.name);
          (PathStat::dir(path.clone(), Dir(path)), None)
        }));
        path_stats.extend(directory.files.iter().map(move |file_node| {
          let path = path_so_far.join(&file_node.name);
          (
            PathStat::file(
              path.clone(),
              File {
                path: path.clone(),
                is_executable: file_node.is_executable,
              },
            ),
            Some((path, file_node.digest.as_ref().unwrap().try_into().unwrap())),
          )
        }));
        path_stats.extend(directory.symlinks.iter().map(move |link_node| {
          let path = path_so_far.join(&link_node.name);
          (
            PathStat::link(
              path.clone(),
              Link {
                path,
                target: link_node.target.clone().into(),
              },
            ),
            None,
          )
        }));
        future::ok(path_stats).boxed()
      })
      .await?;

    let (path_stats, maybe_digests): (Vec<_>, Vec<_>) =
      Iterator::flatten(path_stats_per_directory.into_iter().map(Vec::into_iter)).unzip();
    let file_digests = maybe_digests.into_iter().flatten().collect();

    let tree =
      DigestTrie::from_unique_paths(path_stats.iter().map(|p| p.into()).collect(), &file_digests)?;
    let computed_digest = tree.compute_root_digest();
    if digest.as_digest() != computed_digest {
      return Err(
        format!(
          "Computed digest for Snapshot loaded from store mismatched: {:?} vs {:?}",
          digest.as_digest(),
          computed_digest
        )
        .into(),
      );
    }

    Ok(tree)
  }

  ///
  /// Loads the given directory Digest as a DirectoryDigest, eagerly fetching its tree from
  /// storage. To convert non-eagerly, use `DirectoryDigest::from_persisted_digest`.
  ///
  /// In general, DirectoryDigests should be consumed lazily to avoid fetching from a remote
  /// store unnecessarily, so this method is primarily useful for tests and benchmarks.
  ///
  pub async fn load_directory_digest(&self, digest: Digest) -> Result<DirectoryDigest, StoreError> {
    Ok(DirectoryDigest::new(
      digest,
      self
        .load_digest_trie(DirectoryDigest::from_persisted_digest(digest))
        .await?,
    ))
  }

  ///
  /// Loads a directory proto from the local store, back-filling from remote if necessary.
  ///
  /// Guarantees that if an Ok value is returned, it is valid, and canonical, and its fingerprint
  /// exactly matches that which is requested. Will return an Err if it would return a non-canonical
  /// Directory.
  ///
  pub async fn load_directory(&self, digest: Digest) -> Result<remexec::Directory, StoreError> {
    self
      .load_bytes_with(
        EntryType::Directory,
        digest,
        // Trust that locally stored values were canonical when they were written into the CAS
        // and only verify in debug mode, as it's slightly expensive.
        move |bytes: &[u8]| {
          let directory = remexec::Directory::decode(bytes).map_err(|e| {
            format!("LMDB corruption: Directory bytes for {digest:?} were not valid: {e:?}")
          })?;
          if cfg!(debug_assertions) {
            protos::verify_directory_canonical(digest, &directory)?;
          }
          Ok(directory)
        },
        // Eagerly verify that CAS-returned Directories are canonical, so that we don't write them
        // into our local store.
        Some(&move |bytes| {
          let directory = remexec::Directory::decode(bytes).map_err(|e| {
            format!("CAS returned Directory proto for {digest:?} which was not valid: {e:?}")
          })?;
          protos::verify_directory_canonical(digest, &directory)?;
          Ok(())
        }),
      )
      .await
  }

  ///
  /// Ensures that the directory entries of the given DirectoryDigest is persisted to disk.
  ///
  /// TODO: By the end of #13112, usage of this method should be limited to the writing of cache
  /// entries.
  ///
  pub async fn ensure_directory_digest_persisted(
    &self,
    digest: DirectoryDigest,
  ) -> Result<(), StoreError> {
    let tree = self.load_digest_trie(digest).await?;
    let _ = self.record_digest_trie(tree, true).await?;
    Ok(())
  }

  ///
  /// Loads bytes from remote cas if required and possible (i.e. if remote is configured). Takes
  /// two functions f_local and f_remote. These functions are any validation or transformations you
  /// want to perform on the bytes received from the local and remote cas (if remote is configured).
  ///
  async fn load_bytes_with<
    T: Send + 'static,
    FLocal: Fn(&[u8]) -> Result<T, String> + Clone + Send + Sync + 'static,
  >(
    &self,
    entry_type: EntryType,
    digest: Digest,
    f_local: FLocal,
    f_remote: Option<&(dyn Fn(Bytes) -> Result<(), String> + Send + Sync + 'static)>,
  ) -> Result<T, StoreError> {
    if let Some(bytes_res) = self
      .local
      .load_bytes_with(entry_type, digest, f_local.clone())
      .await?
    {
      return Ok(bytes_res?);
    }

    let remote = self.remote.clone().ok_or_else(|| {
      StoreError::MissingDigest("Was not present in the local store".to_owned(), digest)
    })?;
    remote
      .download_digest_to_local(self.local.clone(), digest, entry_type, f_remote)
      .await?;

    Ok(
      self
        .local
        .load_bytes_with(entry_type, digest, f_local)
        .await?
        .ok_or_else(|| {
          format!("After downloading {digest:?}, the local store claimed that it was not present.")
        })??,
    )
  }

  ///
  /// Ensures that the remote ByteStore has a copy of each passed Fingerprint, including any files
  /// contained in any Directories in the list.
  ///
  /// This method starts by expanding all Digests locally to determine their types. If it cannot
  /// find a Digest locally, it will check whether it exists remotely, without downloading it.
  ///
  /// TODO: This method is only aware of File and Directory typed blobs: in particular, that means
  /// it will not expand Trees to upload the files that they refer to. See #13006.
  ///
  pub fn ensure_remote_has_recursive(
    &self,
    digests: Vec<Digest>,
  ) -> BoxFuture<'static, Result<UploadSummary, StoreError>> {
    let start_time = Instant::now();

    let remote_store = if let Some(ref remote) = self.remote {
      remote.clone()
    } else {
      return futures::future::err(
        "Cannot ensure remote has blobs without a remote"
          .to_owned()
          .into(),
      )
      .boxed();
    };

    let store = self.clone();
    let remote = remote_store.store.clone();
    async move {
      let ingested_digests = store.expand_local_digests(digests.iter()).await?;
      let digests_to_upload =
        if Store::upload_is_faster_than_checking_whether_to_upload(ingested_digests.iter()) {
          ingested_digests.keys().cloned().collect()
        } else {
          remote
            .list_missing_digests(ingested_digests.keys().cloned())
            .await?
        };

      future::try_join_all(
        digests_to_upload
          .iter()
          .cloned()
          .map(|digest| {
            let local = store.local.clone();
            let remote_store = remote_store.clone();
            let maybe_entry_type: Option<EntryType> = ingested_digests[&digest];
            async move {
              let entry_type = if let Some(et) = maybe_entry_type {
                et
              } else {
                return Err(StoreError::MissingDigest(
                  "Did not exist either locally or remotely".to_owned(),
                  digest,
                ));
              };

              remote_store
                .clone()
                .maybe_upload(digest, async move {
                  match local.load_from_fs(digest).await? {
                    Some(path) => {
                      Self::store_fsdb_blob_remote(remote_store.store, digest, path).await?
                    }
                    None => {
                      Self::store_lmdb_blob_remote(local, remote_store.store, entry_type, digest)
                        .await?
                    }
                  };
                  Ok(())
                })
                .await
            }
          })
          .collect::<Vec<_>>(),
      )
      .await?;

      let ingested_file_sizes = ingested_digests.keys().map(|digest| digest.size_bytes);
      let uploaded_file_sizes = digests_to_upload.iter().map(|digest| digest.size_bytes);

      Ok(UploadSummary {
        ingested_file_count: ingested_file_sizes.len(),
        ingested_file_bytes: ingested_file_sizes.sum(),
        uploaded_file_count: uploaded_file_sizes.len(),
        uploaded_file_bytes: uploaded_file_sizes.sum(),
        upload_wall_time: start_time.elapsed(),
      })
    }
    .boxed()
  }

  async fn store_lmdb_blob_remote(
    local: local::ByteStore,
    remote: remote::ByteStore,
    entry_type: EntryType,
    digest: Digest,
  ) -> Result<(), StoreError> {
    // We need to copy the bytes into memory so that they may be used safely in an async
    // future. While this unfortunately increases memory consumption, we prioritize
    // being able to run `remote.store_bytes()` as async. In addition, this is only used
    // for blobs in the LMDB store, most of which are small: large blobs end up in the
    // FSDB store.
    //
    // See https://github.com/pantsbuild/pants/pull/9793 for an earlier implementation
    // that used `Executor.block_on`, which avoided the clone but was blocking.
    let maybe_bytes = local
      .load_bytes_with(entry_type, digest, move |bytes| {
        Bytes::copy_from_slice(bytes)
      })
      .await?;
    match maybe_bytes {
      Some(bytes) => Ok(remote.store_bytes(bytes).await?),
      None => Err(StoreError::MissingDigest(
        format!("Failed to upload {entry_type:?}: Not found in local store",),
        digest,
      )),
    }
  }

  async fn store_fsdb_blob_remote(
    remote: remote::ByteStore,
    digest: Digest,
    path: PathBuf,
  ) -> Result<(), StoreError> {
    let file = tokio::fs::File::open(&path)
      .await
      .map_err(|e| format!("failed to read {digest:?} from {path:?}: {e}"))?;
    remote.store_file(digest, file).await?;
    Ok(())
  }

  ///
  /// Return true if the given directory and file digests are loadable from either the local or remote
  /// Store, without downloading any file content.
  ///
  /// The given directory digests will be recursively expanded, so it is not necessary to
  /// explicitly list their file digests in the file digests list.
  ///
  pub async fn exists_recursive(
    &self,
    directory_digests: impl IntoIterator<Item = DirectoryDigest>,
    file_digests: impl IntoIterator<Item = Digest>,
  ) -> Result<bool, StoreError> {
    // Load directories, which implicitly validates that they exist.
    let digest_tries = future::try_join_all(
      directory_digests
        .into_iter()
        .map(|dd| self.load_digest_trie(dd)),
    )
    .await?;

    // Collect all file digests.
    let mut file_digests = file_digests.into_iter().collect::<HashSet<_>>();
    for digest_trie in digest_tries {
      digest_trie.walk(SymlinkBehavior::Aware, &mut |_, entry| match entry {
        directory::Entry::File(f) => {
          file_digests.insert(f.digest());
        }
        directory::Entry::Symlink(_) | directory::Entry::Directory(_) => (),
      });
    }

    // Filter out file digests that exist locally.
    let missing_locally = self
      .local
      .get_missing_digests(EntryType::File, file_digests)
      .await?;

    // If there are any digests which don't exist locally, check remotely.
    if missing_locally.is_empty() {
      return Ok(true);
    }
    let remote = if let Some(remote) = self.remote.clone() {
      remote
    } else {
      return Ok(false);
    };
    let missing = remote.store.list_missing_digests(missing_locally).await?;

    Ok(missing.is_empty())
  }

  /// Ensure that the files are locally loadable. This will download them from the remote store as
  /// a side effect, if one is configured.
  pub async fn ensure_downloaded(
    &self,
    mut file_digests: HashSet<Digest>,
    directory_digests: HashSet<DirectoryDigest>,
  ) -> Result<(), StoreError> {
    let file_digests_from_directories =
      future::try_join_all(directory_digests.into_iter().map(|dir_digest| async move {
        let mut file_digests_for_dir = Vec::new();
        let trie = self.load_digest_trie(dir_digest).await?;
        trie.walk(SymlinkBehavior::Aware, &mut |_, entry| match entry {
          directory::Entry::File(f) => file_digests_for_dir.push(f.digest()),
          directory::Entry::Symlink(_) | directory::Entry::Directory(_) => (),
        });
        // Also ensure that the directory trie is persisted to disk, not only its file entries.
        self.record_digest_trie(trie, true).await?;
        Ok::<_, StoreError>(file_digests_for_dir)
      }))
      .await?;
    file_digests.extend(file_digests_from_directories.into_iter().flatten());

    let missing_file_digests = self
      .local
      .get_missing_digests(EntryType::File, file_digests)
      .await?;
    if missing_file_digests.is_empty() {
      return Ok(());
    }

    let remote = &self.remote.clone().ok_or_else(|| {
      StoreError::MissingDigest(
        "Was not present in the local store".to_owned(),
        *missing_file_digests.iter().next().unwrap(),
      )
    })?;
    let _ = future::try_join_all(
      missing_file_digests
        .into_iter()
        .map(|file_digest| async move {
          if let Err(e) = remote
            .download_digest_to_local(self.local.clone(), file_digest, EntryType::File, None)
            .await
          {
            log::debug!("Missing file digest from remote store: {:?}", file_digest);
            in_workunit!(
              "missing_file_counter",
              Level::Trace,
              |workunit| async move {
                workunit.increment_counter(Metric::RemoteStoreMissingDigest, 1);
              },
            )
            .await;
            return Err(e);
          }
          Ok(())
        }),
    )
    .await?;
    Ok(())
  }

  /// Load a REv2 Tree from a remote CAS _without_ persisting the embedded Directory protos in
  /// the local store. Tree is used by the REv2 protocol as an optimization for encoding the
  /// the Directory protos that comprise the output directories from a remote execution
  /// reported by an ActionResult.
  ///
  /// Returns an `Option<DirectoryDigest>` representing the `root` of the Tree (if it in fact
  /// exists in the remote CAS).
  ///
  /// This method requires that this Store be configured with a remote CAS, and will return an
  /// error if this is not the case.
  pub async fn load_tree_from_remote(
    &self,
    tree_digest: Digest,
  ) -> Result<Option<DirectoryDigest>, String> {
    let remote = if let Some(ref remote) = self.remote {
      remote
    } else {
      return Err("Cannot load Trees from a remote without a remote".to_owned());
    };

    match remote.store.load_bytes(tree_digest).await? {
      Some(b) => {
        let tree = Tree::decode(b).map_err(|e| format!("protobuf decode error: {e:?}"))?;
        let trie = DigestTrie::try_from(tree)?;
        Ok(Some(trie.into()))
      }
      None => Ok(None),
    }
  }

  pub async fn lease_all_recursively<'a, Ds: Iterator<Item = &'a Digest>>(
    &self,
    digests: Ds,
  ) -> Result<(), StoreError> {
    let reachable_digests_and_types = self.expand_local_digests(digests).await?;
    // Lease all Digests which existed (ignoring any that didn't).
    self
      .local
      .lease_all(
        reachable_digests_and_types
          .into_iter()
          .flat_map(|(digest, maybe_type)| maybe_type.map(|t| (digest, t))),
      )
      .await?;
    Ok(())
  }

  pub async fn garbage_collect(
    &self,
    target_size_bytes: usize,
    shrink_behavior: ShrinkBehavior,
  ) -> Result<(), String> {
    match self.local.shrink(target_size_bytes, shrink_behavior).await {
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
      Err(err) => Err(format!("Garbage collection failed: {err:?}")),
    }
  }

  ///
  /// To check if it might be faster to upload the digests recursively
  /// vs checking if the files are present first.
  ///
  /// The values are guesses, feel free to tweak them.
  ///
  fn upload_is_faster_than_checking_whether_to_upload<'a>(
    digests: impl Iterator<Item = (&'a Digest, &'a Option<EntryType>)>,
  ) -> bool {
    let mut num_digests = 0;
    let mut num_bytes = 0;
    for (digest, maybe_type) in digests {
      if maybe_type.is_none() {
        // We cannot upload this entry, because we don't have it locally.
        return false;
      }
      num_digests += 1;
      num_bytes += digest.size_bytes;
      if num_digests >= 3 || num_bytes >= (1024 * 1024) {
        return false;
      }
    }
    // There were fewer than 3 digests, and they were less than the threshold.
    true
  }

  ///
  /// Return all Digests locally reachable from the given root Digests (which may represent either
  /// Files or Directories).
  ///
  /// This method will return `None` for either a root or inner Digest if it does not exist.
  ///
  async fn expand_local_digests<'a, Ds: Iterator<Item = &'a Digest>>(
    &self,
    digests: Ds,
  ) -> Result<HashMap<Digest, Option<EntryType>>, StoreError> {
    // Expand each digest into either a single digest (Left), or a collection of recursive digests
    // below a directory (Right).
    let expanded_digests: Vec<Either<_, _>> = future::try_join_all(
      digests
        .map(|digest| {
          let store = self.clone();
          async move {
            let entry_type = store
              .local
              .entry_type(digest.hash)
              .await
              .map_err(|e| format!("Failed to expand digest {digest:?}: {e}"))?;
            match entry_type {
              Some(EntryType::File) => Ok(Either::Left((*digest, Some(EntryType::File)))),
              Some(EntryType::Directory) => match store.expand_directory(*digest).await {
                Ok(entries) => Ok(Either::Right(entries)),
                Err(StoreError::MissingDigest(_, digest)) => Ok(Either::Left((digest, None))),
                Err(e) => Err(e),
              },
              None => Ok(Either::Left((*digest, None))),
            }
          }
        })
        .collect::<Vec<_>>(),
    )
    .await?;

    let mut result = HashMap::with_capacity(expanded_digests.len());
    for e in expanded_digests {
      match e {
        Either::Left((digest, maybe_type)) => {
          result.insert(digest, maybe_type);
        }
        Either::Right(reachable_digests) => {
          result.extend(
            reachable_digests
              .into_iter()
              .map(|(digest, t)| (digest, Some(t))),
          );
        }
      }
    }
    Ok(result)
  }

  fn expand_directory(
    &self,
    digest: Digest,
  ) -> BoxFuture<'static, Result<HashMap<Digest, EntryType>, StoreError>> {
    self
      .walk(digest, |_, _, digest, directory| {
        let mut digest_types = vec![(digest, EntryType::Directory)];
        for file in &directory.files {
          let file_digest = try_future!(require_digest(file.digest.as_ref()));
          digest_types.push((file_digest, EntryType::File));
        }
        future::ok(digest_types).boxed()
      })
      .map(|digest_pairs_per_directory| {
        digest_pairs_per_directory.map(|xs| {
          xs.into_iter()
            .flat_map(|x| x.into_iter())
            .collect::<HashMap<_, _>>()
        })
      })
      .boxed()
  }

  ///
  /// Lays out the directory and all of its contents (files and directories) on disk so that a
  /// process which uses the directory structure can run.
  ///
  /// Although `Directory` has internally unique paths, `materialize_directory` can be used with
  /// an existing destination directory, meaning that directory and file creation must be
  /// idempotent.
  ///
  /// If the destination (more specifically, the given parent directory of the destination, for
  /// memoization purposes) is hardlinkable from the local store, and `!force_mutable`, hardlinks
  /// may be used for large files which are not listed in `mutable_paths`.
  ///
  pub async fn materialize_directory(
    &self,
    destination: PathBuf,
    destination_root: &Path,
    digest: DirectoryDigest,
    force_mutable: bool,
    mutable_paths: &BTreeSet<RelativePath>,
    perms: Permissions,
  ) -> Result<(), StoreError> {
    debug_assert!(
      destination.starts_with(destination_root),
      "The destination root must be a parent directory of the destination."
    );

    // Load the DigestTrie for the digest, and convert it into a mapping between a fully qualified
    // parent path and its children.
    let mut parent_to_child = HashMap::new();
    let tree = self.load_digest_trie(digest).await?;
    tree.walk(SymlinkBehavior::Aware, &mut |path, entry| {
      if let Some(parent) = path.parent() {
        parent_to_child
          .entry(destination.join(parent))
          .or_insert_with(Vec::new)
          .push(entry.clone());
      }
    });

    let mut mutable_path_ancestors = BTreeSet::new();
    for relpath in mutable_paths {
      mutable_path_ancestors.extend(relpath.ancestors().map(|p| destination.join(p)));
    }

    // Create the root, and determine what filesystem it and the store are on.
    let destination_is_hardlinkable = {
      let (_, destination_is_hardlinkable) = tokio::try_join!(
        tokio::fs::create_dir_all(&destination)
          .map_err(|e| format!("Failed to create directory {}: {e}", destination.display())),
        self.local.is_hardlinkable_destination(destination_root)
      )?;
      destination_is_hardlinkable
    };

    self
      .materialize_directory_children(
        destination,
        true,
        force_mutable,
        destination_is_hardlinkable,
        &parent_to_child,
        &mutable_path_ancestors,
        perms,
      )
      .await
  }

  fn materialize_directory_children<'a>(
    &self,
    destination: PathBuf,
    is_root: bool,
    force_mutable: bool,
    can_hardlink: bool,
    parent_to_child: &'a HashMap<PathBuf, Vec<directory::Entry>>,
    mutable_paths: &'a BTreeSet<PathBuf>,
    perms: Permissions,
  ) -> BoxFuture<'a, Result<(), StoreError>> {
    let store = self.clone();
    async move {
      if !is_root {
        // NB: Although we know that all parent directories already exist, we use `create_dir_all`
        // because it succeeds even if _this_ directory already exists (which it might, if we're
        // materializing atop an existing directory structure).
        tokio::fs::create_dir_all(&destination)
          .await
          .map_err(|e| format!("Failed to create directory {}: {e}", destination.display()))?;
      }

      if let Some(children) = parent_to_child.get(&destination) {
        let mut child_futures = Vec::new();
        for child in children {
          let path = destination.join(child.name().as_ref());
          let store = store.clone();
          child_futures.push(async move {
            let can_be_immutable = !force_mutable && can_hardlink && !mutable_paths.contains(&path);

            match child {
              directory::Entry::File(f) => {
                store
                  .materialize_file_maybe_hardlink(
                    path,
                    f.digest(),
                    perms,
                    f.is_executable(),
                    can_be_immutable,
                  )
                  .await
              }
              directory::Entry::Symlink(s) => {
                store
                  .materialize_symlink(path, s.target().to_str().unwrap().to_string())
                  .await
              }
              directory::Entry::Directory(_) => {
                store
                  .materialize_directory_children(
                    path.clone(),
                    false,
                    mutable_paths.contains(&path) || force_mutable,
                    can_hardlink,
                    parent_to_child,
                    mutable_paths,
                    perms,
                  )
                  .await
              }
            }
          });
        }
        let _ = future::try_join_all(child_futures).await?;
      }

      if perms == Permissions::ReadOnly {
        tokio::fs::set_permissions(&destination, std::fs::Permissions::from_mode(0o555))
          .await
          .map_err(|e| {
            format!(
              "Failed to set permissions for {}: {}",
              destination.display(),
              e
            )
          })?;
      }
      Ok(())
    }
    .boxed()
  }

  async fn materialize_file_maybe_hardlink(
    &self,
    destination: PathBuf,
    digest: Digest,
    perms: Permissions,
    is_executable: bool,
    can_be_immutable: bool,
  ) -> Result<(), StoreError> {
    let hardlink_tgt = if can_be_immutable {
      self.local.load_from_fs(digest).await?
    } else {
      None
    };
    match hardlink_tgt {
      Some(path) => {
        self
          .materialize_hardlink(destination, path.to_str().unwrap().to_string())
          .await
      }
      None => {
        self
          .materialize_file(destination, digest, perms, is_executable)
          .await
      }
    }
  }

  async fn materialize_file(
    &self,
    destination: PathBuf,
    digest: Digest,
    perms: Permissions,
    is_executable: bool,
  ) -> Result<(), StoreError> {
    let mode = match perms {
      Permissions::ReadOnly if is_executable => 0o555,
      Permissions::ReadOnly => 0o444,
      Permissions::Writable if is_executable => 0o755,
      Permissions::Writable => 0o644,
    };
    match self.local.load_from_fs(digest).await? {
      Some(path) => {
        tokio::fs::copy(&path, &destination).await.map_err(|e| {
          format!(
            "Error copying bytes from {} to {}: {e}",
            path.display(),
            destination.display()
          )
        })?;
        tokio::fs::set_permissions(destination, FSPermissions::from_mode(mode))
          .await
          .map_err(|e| format!("Error setting permissions on {}: {e}", path.display()))?;
        Ok(())
      }
      None => {
        self
          .load_file_bytes_with(digest, move |bytes| {
            let mut f = OpenOptions::new()
              .create(true)
              .write(true)
              .truncate(true)
              .mode(mode)
              .open(&destination)
              .map_err(|e| {
                format!(
                  "Error opening file {} for writing: {:?}",
                  destination.display(),
                  e
                )
              })?;
            f.write_all(bytes)
              .map_err(|e| format!("Error writing file {}: {:?}", destination.display(), e))?;
            Ok(())
          })
          .await?
      }
    }
  }

  pub async fn materialize_symlink(
    &self,
    destination: PathBuf,
    target: String,
  ) -> Result<(), StoreError> {
    // Overwriting a symlink, even with another symlink, fails if it exists. This can occur when
    // materializing to a fixed directory like dist/. To avoid pessimising the more common case (no
    // overwrite, e.g. materializing to a temp dir), only remove after noticing a failure.
    //
    // NB. #17758, #18849: this is a work-around for inaccurate management of the contents of dist/.
    for first in [true, false] {
      match symlink(&target, &destination).await {
        Ok(()) => break,
        Err(e) if first && e.kind() == std::io::ErrorKind::AlreadyExists => {
          tokio::fs::remove_dir_all(&destination).await.map_err(|e| {
            format!(
              "Failed to remove existing item at {} when creating symlink to {target} there: {e}",
              destination.display()
            )
          })?
        }
        Err(e) => Err(format!(
          "Failed to create symlink to {target} at {}: {e}",
          destination.display()
        ))?,
      }
    }
    Ok(())
  }

  pub async fn materialize_hardlink(
    &self,
    destination: PathBuf,
    target: String,
  ) -> Result<(), StoreError> {
    // On macOS, copy uses a copy-on-write syscall (fclonefileat) which creates a disconnected
    // clone. It is more defensive than a hardlink, but has the same requirement that the source
    // and destination filesystem are the same.
    //
    // It also has the benefit of playing nicely with Docker for macOS file virtualization: see
    // #18162.
    #[cfg(target_os = "macos")]
    copy(&target, &destination).await.map_err(|e| {
      format!(
        "Failed to copy from {target} to {}: {e}",
        destination.display()
      )
    })?;
    #[cfg(not(target_os = "macos"))]
    hard_link(&target, &destination).await.map_err(|e| {
      format!(
        "Failed to create hardlink to {target} at {}: {e}",
        destination.display()
      )
    })?;
    Ok(())
  }

  ///
  /// Returns files sorted by their path.
  ///
  pub async fn contents_for_directory(
    &self,
    digest: DirectoryDigest,
  ) -> Result<Vec<FileContent>, StoreError> {
    let mut files = Vec::new();
    self
      .load_digest_trie(digest)
      .await?
      .walk(SymlinkBehavior::Oblivious, &mut |path, entry| match entry {
        directory::Entry::File(f) => files.push((path.to_owned(), f.digest(), f.is_executable())),
        directory::Entry::Symlink(_) => (),
        directory::Entry::Directory(_) => (),
      });

    future::try_join_all(files.into_iter().map(|(path, digest, is_executable)| {
      let store = self.clone();
      async move {
        let content = store
          .load_file_bytes_with(digest, Bytes::copy_from_slice)
          .await
          .map_err(|e| e.enrich(&format!("Couldn't find file contents for {path:?}")))?;
        Ok(FileContent {
          path,
          content,
          is_executable,
        })
      }
    }))
    .await
  }

  ///
  /// Returns indirect references to files in a Digest sorted by their path.
  ///
  pub async fn entries_for_directory(
    &self,
    digest: DirectoryDigest,
  ) -> Result<Vec<DigestEntry>, StoreError> {
    if digest == *EMPTY_DIRECTORY_DIGEST {
      return Ok(vec![]);
    }

    let mut entries = Vec::new();
    self.load_digest_trie(digest).await?.walk(
      SymlinkBehavior::Aware,
      &mut |path, entry| match entry {
        directory::Entry::File(f) => {
          entries.push(DigestEntry::File(FileEntry {
            path: path.to_owned(),
            digest: f.digest(),
            is_executable: f.is_executable(),
          }));
        }
        directory::Entry::Symlink(s) => {
          entries.push(DigestEntry::Symlink(SymlinkEntry {
            path: path.to_owned(),
            target: s.target().to_path_buf(),
          }));
        }
        directory::Entry::Directory(d) => {
          // Only report a directory if it is a leaf node. (The caller is expected to create parent
          // directories for both files and empty leaf directories.)
          if d.tree().entries().is_empty() {
            entries.push(DigestEntry::EmptyDirectory(path.to_owned()));
          }
        }
      },
    );

    Ok(entries)
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
        &remexec::Directory,
      ) -> future::BoxFuture<'static, Result<T, String>>
      + Send
      + Sync
      + 'static,
  >(
    &self,
    digest: Digest,
    f: F,
  ) -> BoxFuture<'static, Result<Vec<T>, StoreError>> {
    let f = Arc::new(f);
    let accumulator = Arc::new(Mutex::new(Vec::new()));
    self
      .walk_helper(digest, PathBuf::new(), f, accumulator.clone())
      .map(|r| {
        r.map(|_| {
          Arc::try_unwrap(accumulator)
            .unwrap_or_else(|_| panic!("walk_helper violated its contract."))
            .into_inner()
        })
      })
      .boxed()
  }

  fn walk_helper<
    T: Send + 'static,
    F: Fn(
        &Store,
        &PathBuf,
        Digest,
        &remexec::Directory,
      ) -> future::BoxFuture<'static, Result<T, String>>
      + Send
      + Sync
      + 'static,
  >(
    &self,
    digest: Digest,
    path_so_far: PathBuf,
    f: Arc<F>,
    accumulator: Arc<Mutex<Vec<T>>>,
  ) -> BoxFuture<'static, Result<(), StoreError>> {
    let store = self.clone();
    let res = async move {
      let directory = store.load_directory(digest).await.map_err(|e| {
        e.enrich(&format!(
          "Could not walk unknown directory at {path_so_far:?}"
        ))
      })?;
      let result_for_directory = f(&store, &path_so_far, digest, &directory).await?;
      {
        let mut accumulator = accumulator.lock();
        accumulator.push(result_for_directory);
      }
      future::try_join_all(
        directory
          .directories
          .iter()
          .map(move |dir_node| {
            let subdir_digest = try_future!(require_digest(dir_node.digest.as_ref()));
            let path = path_so_far.join(dir_node.name.clone());
            store.walk_helper(subdir_digest, path, f.clone(), accumulator.clone())
          })
          .collect::<Vec<_>>(),
      )
      .await?;
      Ok(())
    };
    res.boxed()
  }

  pub async fn all_local_digests(&self, entry_type: EntryType) -> Result<Vec<Digest>, String> {
    self.local.all_digests(entry_type).await
  }
}

#[async_trait]
impl SnapshotOps for Store {
  type Error = StoreError;

  async fn load_file_bytes_with<
    T: Send + 'static,
    F: Fn(&[u8]) -> T + Clone + Send + Sync + 'static,
  >(
    &self,
    digest: Digest,
    f: F,
  ) -> Result<T, StoreError> {
    Store::load_file_bytes_with(self, digest, f).await
  }

  async fn load_digest_trie(&self, digest: DirectoryDigest) -> Result<DigestTrie, StoreError> {
    Store::load_digest_trie(self, digest).await
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
