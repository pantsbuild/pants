// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use super::{EntryType, ShrinkBehavior};

use core::future::Future;
use std::collections::{BinaryHeap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bytes::Bytes;
use futures::future::{self, join_all, try_join, try_join_all};
use hashing::{
  async_copy_and_hash, async_verified_copy, AgedFingerprint, Digest, Fingerprint, EMPTY_DIGEST,
};
use parking_lot::Mutex;
use sharded_lmdb::ShardedLmdb;
use std::os::unix::fs::PermissionsExt;
use task_executor::Executor;
use tempfile::Builder;
use tokio::fs::hard_link;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWriteExt};
use tokio::sync::{Semaphore, SemaphorePermit};
use workunit_store::ObservationMetric;

/// How big a file must be to be stored as a file on disk.
// NB: These numbers were chosen after micro-benchmarking the code on one machine at the time of
// writing. They were chosen using a rough equation from the microbenchmarks that are optimized
// for somewhere between 2 and 3 uses of the corresponding entry to "break even".
const LARGE_FILE_SIZE_LIMIT: usize = 512 * 1024;

/// Trait for the underlying storage, which is either a ShardedLMDB or a ShardedFS.
#[async_trait]
trait UnderlyingByteStore {
  async fn exists_batch(
    &self,
    fingerprints: Vec<Fingerprint>,
  ) -> Result<HashSet<Fingerprint>, String>;

  async fn exists(&self, fingerprint: Fingerprint) -> Result<bool, String> {
    let exists = self.exists_batch(vec![fingerprint]).await?;
    Ok(exists.contains(&fingerprint))
  }

  async fn lease(&self, fingerprint: Fingerprint) -> Result<(), String>;

  async fn remove(&self, fingerprint: Fingerprint) -> Result<bool, String>;

  async fn store_bytes_batch(
    &self,
    items: Vec<(Fingerprint, Bytes)>,
    initial_lease: bool,
  ) -> Result<(), String>;

  async fn store(
    &self,
    initial_lease: bool,
    src_is_immutable: bool,
    expected_digest: Digest,
    file_source: &FileSource,
    src: PathBuf,
  ) -> Result<(), String>;

  async fn load_bytes_with<
    T: Send + 'static,
    F: FnMut(&[u8]) -> Result<T, String> + Send + Sync + 'static,
  >(
    &self,
    fingerprint: Fingerprint,
    mut f: F,
  ) -> Result<Option<T>, String>;

  async fn aged_fingerprints(&self) -> Result<Vec<AgedFingerprint>, String>;

  async fn all_digests(&self) -> Result<Vec<Digest>, String> {
    let fingerprints = self.aged_fingerprints().await?;
    Ok(
      fingerprints
        .into_iter()
        .map(|fingerprint| Digest {
          hash: fingerprint.fingerprint,
          size_bytes: fingerprint.size_bytes,
        })
        .collect(),
    )
  }
}

#[async_trait]
impl UnderlyingByteStore for ShardedLmdb {
  async fn exists_batch(
    &self,
    fingerprints: Vec<Fingerprint>,
  ) -> Result<HashSet<Fingerprint>, String> {
    self.exists_batch(fingerprints).await
  }

  async fn lease(&self, fingerprint: Fingerprint) -> Result<(), String> {
    self.lease(fingerprint).await
  }

  async fn remove(&self, fingerprint: Fingerprint) -> Result<bool, String> {
    self.remove(fingerprint).await
  }

  async fn store_bytes_batch(
    &self,
    items: Vec<(Fingerprint, Bytes)>,
    initial_lease: bool,
  ) -> Result<(), String> {
    self.store_bytes_batch(items, initial_lease).await
  }
  async fn store(
    &self,
    initial_lease: bool,
    src_is_immutable: bool,
    expected_digest: Digest,
    _file_source: &FileSource,
    src: PathBuf,
  ) -> Result<(), String> {
    self
      .store(
        initial_lease,
        src_is_immutable,
        expected_digest,
        move || {
          // NB: This file access is bounded by the number of blocking threads on the runtime, and
          // so we don't bother to acquire against the file handle limit in this case.
          std::fs::File::open(&src)
        },
      )
      .await
  }

  async fn load_bytes_with<
    T: Send + 'static,
    F: FnMut(&[u8]) -> Result<T, String> + Send + Sync + 'static,
  >(
    &self,
    fingerprint: Fingerprint,
    f: F,
  ) -> Result<Option<T>, String> {
    self.load_bytes_with(fingerprint, f).await
  }

  async fn aged_fingerprints(&self) -> Result<Vec<AgedFingerprint>, String> {
    self.all_fingerprints().await
  }
}

// We shard so there isn't a plethora of entries in one single dir.
//
// TODO: Add Arc'd inner struct to reduce clone costs.
#[derive(Debug, Clone)]
pub(crate) struct ShardedFSDB {
  root: PathBuf,
  executor: Executor,
  lease_time: Duration,
  dest_initializer: Arc<Mutex<HashMap<Fingerprint, Arc<OnceCell<()>>>>>,
  // A cache of whether destination root directories are hardlinkable from the fsdb.
  hardlinkable_destinations: Arc<Mutex<HashMap<PathBuf, Arc<OnceCell<bool>>>>>,
}

enum VerifiedCopyError {
  CopyFailure(String),
  DoesntMatch,
}

impl From<String> for VerifiedCopyError {
  fn from(err: String) -> Self {
    Self::CopyFailure(err)
  }
}

impl ShardedFSDB {
  pub(crate) fn get_path(&self, fingerprint: Fingerprint) -> PathBuf {
    let hex = fingerprint.to_hex();
    self.root.join(hex.get(0..2).unwrap()).join(hex)
  }

  async fn is_hardlinkable_destination(&self, destination: &Path) -> Result<bool, String> {
    let cell = {
      let mut cells = self.hardlinkable_destinations.lock();
      if let Some(cell) = cells.get(destination) {
        cell.clone()
      } else {
        let cell = Arc::new(OnceCell::new());
        cells.insert(destination.to_owned(), cell.clone());
        cell
      }
    };

    if let Some(res) = cell.get() {
      return Ok(*res);
    }

    let fsdb = self.clone();
    let dst_parent_dir = destination.to_owned();
    cell
      .get_or_try_init(async move {
        let src_display = fsdb.root.display().to_string();
        let dst_display = dst_parent_dir.display().to_string();
        tokio::fs::create_dir_all(&dst_parent_dir)
          .await
          .map_err(|e| format!("Failed to create directory: {e}"))?;
        let (src_file, dst_dir) = fsdb
          .executor
          .spawn_blocking(
            move || {
              let src_file = Builder::new()
                .suffix(".hardlink_canary")
                .tempfile_in(&fsdb.root)
                .map_err(|e| format!("Failed to create hardlink canary file: {e}"))?;
              let dst_dir = Builder::new()
                .suffix(".hardlink_canary")
                .tempdir_in(dst_parent_dir)
                .map_err(|e| format!("Failed to create hardlink canary dir: {e}"))?;
              Ok((src_file, dst_dir))
            },
            |e| Err(format!("hardlink canary temp files task failed: {e}")),
          )
          .await?;
        let dst_file = dst_dir.path().join("hard_link");
        let is_hardlinkable = hard_link(src_file, dst_file).await.is_ok();
        log::debug!("{src_display} -> {dst_display} hardlinkable: {is_hardlinkable}");
        Ok(is_hardlinkable)
      })
      .await
      .copied()
  }

  async fn bytes_writer(
    mut file: tokio::fs::File,
    bytes: &Bytes,
  ) -> Result<tokio::fs::File, String> {
    file
      .write_all(bytes)
      .await
      .map_err(|e| format!("Failed to write bytes: {e}"))?;
    Ok(file)
  }

  async fn verified_copier<R>(
    mut file: tokio::fs::File,
    expected_digest: Digest,
    src_is_immutable: bool,
    mut reader: R,
  ) -> Result<tokio::fs::File, VerifiedCopyError>
  where
    R: AsyncRead + Unpin,
  {
    let matches = async_verified_copy(expected_digest, src_is_immutable, &mut reader, &mut file)
      .await
      .map_err(|e| VerifiedCopyError::CopyFailure(format!("Failed to copy bytes: {e}")))?;
    if matches {
      Ok(file)
    } else {
      Err(VerifiedCopyError::DoesntMatch)
    }
  }

  pub(crate) async fn write_using<E, F, Fut>(
    &self,
    fingerprint: Fingerprint,
    writer_func: F,
  ) -> Result<(), E>
  where
    F: FnOnce(tokio::fs::File) -> Fut,
    Fut: Future<Output = Result<tokio::fs::File, E>>,
    // NB: The error type must be convertible from a string
    E: std::convert::From<std::string::String>,
  {
    let cell = self
      .dest_initializer
      .lock()
      .entry(fingerprint)
      .or_default()
      .clone();
    cell
      .get_or_try_init(async {
        let dest_path = self.get_path(fingerprint);
        tokio::fs::create_dir_all(dest_path.parent().unwrap())
          .await
          .map_err(|e| format! {"Failed to create local store subdirectory {dest_path:?}: {e}"})?;

        let dest_path2 = dest_path.clone();
        // Make the tempfile in the same dir as the final file so that materializing the final file doesn't
        // have to worry about parent dirs.
        let named_temp_file = self
          .executor
          .spawn_blocking(
            move || {
              Builder::new()
                .suffix(".tmp")
                .tempfile_in(dest_path2.parent().unwrap())
                .map_err(|e| format!("Failed to create temp file: {e}"))
            },
            |e| Err(format!("temp file creation task failed: {e}")),
          )
          .await?;
        let (std_file, tmp_path) = named_temp_file
          .keep()
          .map_err(|e| format!("Failed to keep temp file: {e}"))?;

        match writer_func(std_file.into()).await {
          Ok(mut tokio_file) => {
            tokio_file
              .shutdown()
              .await
              .map_err(|e| format!("Failed to shutdown {tmp_path:?}: {e}"))?;
            tokio::fs::set_permissions(&tmp_path, std::fs::Permissions::from_mode(0o555))
              .await
              .map_err(|e| format!("Failed to set permissions on {:?}: {e}", tmp_path))?;
            // NB: Syncing metadata to disk ensures the `hard_link` we do later has the opportunity
            // to succeed. Otherwise, if later when we try to `hard_link` the metadata isn't
            // persisted to disk, we'll get `No such file or directory`.
            // See https://github.com/pantsbuild/pants/pull/18768
            tokio_file
              .sync_all()
              .await
              .map_err(|e| format!("Failed to sync {tmp_path:?}: {e}"))?;
            tokio::fs::rename(tmp_path.clone(), dest_path.clone())
              .await
              .map_err(|e| format!("Error while renaming: {e}."))?;
            Ok(())
          }
          Err(e) => {
            let _ = tokio::fs::remove_file(tmp_path).await;
            Err(e)
          }
        }
      })
      .await
      .cloned()
  }
}

#[async_trait]
impl UnderlyingByteStore for ShardedFSDB {
  async fn exists_batch(
    &self,
    fingerprints: Vec<Fingerprint>,
  ) -> Result<HashSet<Fingerprint>, String> {
    let results = join_all(
      fingerprints
        .iter()
        .map(|fingerprint| tokio::fs::metadata(self.get_path(*fingerprint))),
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

    Ok(HashSet::from_iter(existing))
  }

  async fn lease(&self, fingerprint: Fingerprint) -> Result<(), String> {
    let path = self.get_path(fingerprint);
    self
      .executor
      .spawn_blocking(
        move || {
          fs_set_times::set_mtime(&path, fs_set_times::SystemTimeSpec::SymbolicNow)
            .map_err(|e| format!("Failed to extend mtime of {path:?}: {e}"))
        },
        |e| Err(format!("`lease` task failed: {e}")),
      )
      .await
  }

  async fn remove(&self, fingerprint: Fingerprint) -> Result<bool, String> {
    let _ = self.dest_initializer.lock().remove(&fingerprint);
    Ok(
      tokio::fs::remove_file(self.get_path(fingerprint))
        .await
        .is_ok(),
    )
  }

  async fn store_bytes_batch(
    &self,
    items: Vec<(Fingerprint, Bytes)>,
    _initial_lease: bool,
  ) -> Result<(), String> {
    try_join_all(items.iter().map(|(fingerprint, bytes)| async move {
      self
        .write_using(*fingerprint, |file| Self::bytes_writer(file, bytes))
        .await?;
      Ok::<(), String>(())
    }))
    .await?;

    Ok(())
  }

  async fn store(
    &self,
    _initial_lease: bool,
    src_is_immutable: bool,
    expected_digest: Digest,
    file_source: &FileSource,
    src: PathBuf,
  ) -> Result<(), String> {
    let mut attempts = 0;
    loop {
      let (reader, _permit) = file_source
        .open_readonly(&src)
        .await
        .map_err(|e| format!("Failed to open {src:?}: {e}"))?;

      // TODO: Consider using `fclonefileat` on macOS or checking for same filesystem+rename on Linux,
      // which would skip actual copying (read+write), and instead just require verifying the
      // resulting content after the syscall (read only).
      let copy_result = self
        .write_using(expected_digest.hash, |file| {
          Self::verified_copier(file, expected_digest, src_is_immutable, reader)
        })
        .await;
      let should_retry = match copy_result {
        Ok(()) => Ok(false),
        Err(VerifiedCopyError::CopyFailure(s)) => Err(s),
        Err(VerifiedCopyError::DoesntMatch) => Ok(true),
      };

      if should_retry? {
        attempts += 1;
        let msg = format!("Input {src:?} changed while reading.");
        log::debug!("{}", msg);
        if attempts > 10 {
          return Err(format!("Failed to store {src:?}."));
        }
      } else {
        break;
      }
    }

    Ok(())
  }

  async fn load_bytes_with<
    T: Send + 'static,
    F: FnMut(&[u8]) -> Result<T, String> + Send + Sync + 'static,
  >(
    &self,
    fingerprint: Fingerprint,
    mut f: F,
  ) -> Result<Option<T>, String> {
    if let Ok(mut file) = tokio::fs::File::open(self.get_path(fingerprint)).await {
      // TODO: Use mmap instead of copying into user-space.
      let mut contents: Vec<u8> = vec![];
      file
        .read_to_end(&mut contents)
        .await
        .map_err(|e| format!("Failed to load large file into memory: {e}"))?;
      Ok(Some(f(&contents[..])?))
    } else {
      Ok(None)
    }
  }

  async fn aged_fingerprints(&self) -> Result<Vec<AgedFingerprint>, String> {
    // NB: The ShardLmdb implementation stores a lease time in the future, and then compares the
    // current time to the stored lease time for a fingerprint to determine how long ago it
    // expired. Rather than setting `mtimes` in the future, this implementation instead considers a
    // file to be expired if its mtime is outside of the lease time window.
    let root = self.root.clone();
    let expiration_time = SystemTime::now() - self.lease_time;
    self
      .executor
      .spawn_blocking(
        move || {
          let maybe_shards = std::fs::read_dir(&root);
          let mut fingerprints = vec![];
          if let Ok(shards) = maybe_shards {
            for entry in shards {
              let shard = entry.map_err(|e| format!("Error iterating dir {root:?}: {e}."))?;
              let large_files = std::fs::read_dir(shard.path())
                .map_err(|e| format!("Failed to read shard directory: {e}."))?;
              for entry in large_files {
                let large_file = entry.map_err(|e| {
                  format!("Error iterating dir {:?}: {e}", shard.path().file_name())
                })?;
                let path = large_file.path();
                if path.extension().is_some() {
                  continue; // NB: This is a tempfile
                }

                let hash = path.file_name().unwrap().to_str().unwrap();
                let (length, mtime) = large_file
                  .metadata()
                  .and_then(|metadata| {
                    let length = metadata.len();
                    let mtime = metadata.modified()?;
                    Ok((length, mtime))
                  })
                  .map_err(|e| format!("Could not access metadata for {path:?}: {e}"))?;

                let expired_seconds_ago = expiration_time
                  .duration_since(mtime)
                  .map(|t| t.as_secs())
                  // 0 indicates unexpired.
                  .unwrap_or(0);

                fingerprints.push(AgedFingerprint {
                  expired_seconds_ago,
                  fingerprint: Fingerprint::from_hex_string(hash)
                    .map_err(|e| format!("Invalid file store entry at {path:?}: {e}"))?,
                  size_bytes: length as usize,
                });
              }
            }
          }
          Ok(fingerprints)
        },
        |e| Err(format!("`aged_fingerprints` task failed: {e}")),
      )
      .await
  }
}

/// A best-effort limit on the number of concurrent attempts to open files.
#[derive(Debug)]
struct FileSource {
  open_files: Semaphore,
}

impl FileSource {
  async fn open_readonly(&self, path: &Path) -> Result<(tokio::fs::File, SemaphorePermit), String> {
    let permit = self
      .open_files
      .acquire()
      .await
      .map_err(|e| format!("Failed to acquire permit to open file: {e}"))?;
    let file = tokio::fs::File::open(path)
      .await
      .map_err(|e| e.to_string())?;
    Ok((file, permit))
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
  file_lmdb: Result<Arc<ShardedLmdb>, String>,
  directory_lmdb: Result<Arc<ShardedLmdb>, String>,
  file_fsdb: ShardedFSDB,
  file_source: FileSource,
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
    let lmdb_files_root = root.join("files");
    let lmdb_directories_root = root.join("directories");
    let fsdb_files_root = root.join("immutable").join("files");

    std::fs::create_dir_all(root)
      .map_err(|e| format!("Failed to create {}: {e}", root.display()))?;
    std::fs::create_dir_all(&fsdb_files_root)
      .map_err(|e| format!("Failed to create {}: {e}", fsdb_files_root.display()))?;

    Ok(ByteStore {
      inner: Arc::new(InnerStore {
        file_lmdb: ShardedLmdb::new(
          lmdb_files_root,
          options.files_max_size_bytes,
          executor.clone(),
          options.lease_time,
          options.shard_count,
        )
        .map(Arc::new),
        directory_lmdb: ShardedLmdb::new(
          lmdb_directories_root,
          options.directories_max_size_bytes,
          executor.clone(),
          options.lease_time,
          options.shard_count,
        )
        .map(Arc::new),
        file_fsdb: ShardedFSDB {
          executor: executor,
          root: fsdb_files_root,
          lease_time: options.lease_time,
          dest_initializer: Arc::new(Mutex::default()),
          hardlinkable_destinations: Arc::new(Mutex::default()),
        },
        // NB: This is much larger than the number of cores on modern machines, but still small
        // enough to be a "reasonable" number of open files to set in `ulimit`. This is a
        // best-effort limit (because it does-not/cannot cover all of the places where we open
        // files).
        file_source: FileSource {
          open_files: Semaphore::new(1024),
        },
      }),
    })
  }

  pub async fn is_hardlinkable_destination(&self, destination: &Path) -> Result<bool, String> {
    self
      .inner
      .file_fsdb
      .is_hardlinkable_destination(destination)
      .await
  }

  pub async fn entry_type(&self, fingerprint: Fingerprint) -> Result<Option<EntryType>, String> {
    if fingerprint == EMPTY_DIGEST.hash {
      // Technically this is valid as both; choose Directory in case a caller is checking whether
      // it _can_ be a Directory.
      return Ok(Some(EntryType::Directory));
    }

    // In parallel, check for the given fingerprint in all databases.
    let directory_lmdb = self.inner.directory_lmdb.clone()?;
    let is_lmdb_dir = directory_lmdb.exists(fingerprint);
    let file_lmdb = self.inner.file_lmdb.clone()?;
    let is_lmdb_file = file_lmdb.exists(fingerprint);
    let is_fsdb_file = self.inner.file_fsdb.exists(fingerprint);

    // TODO: Could technically use select to return slightly more quickly with the first
    // affirmative answer, but this is simpler.
    match future::try_join3(is_lmdb_dir, is_lmdb_file, is_fsdb_file).await? {
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
      if ByteStore::should_use_fsdb(entry_type, digest.size_bytes) {
        self.inner.file_fsdb.lease(digest.hash).await?;
      } else {
        let dbs = match entry_type {
          EntryType::File => self.inner.file_lmdb.clone(),
          EntryType::Directory => self.inner.directory_lmdb.clone(),
        };
        dbs?
          .lease(digest.hash)
          .await
          .map_err(|err| format!("Error leasing digest {digest:?}: {err}"))?;
      }
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
  pub async fn shrink(
    &self,
    target_bytes: usize,
    shrink_behavior: ShrinkBehavior,
  ) -> Result<usize, String> {
    let mut used_bytes: usize = 0;
    let mut fingerprints_by_expired_ago = BinaryHeap::new();

    fingerprints_by_expired_ago.extend(
      self
        .inner
        .file_lmdb
        .clone()?
        .aged_fingerprints()
        .await?
        .into_iter()
        .map(|fingerprint| {
          used_bytes += fingerprint.size_bytes;
          (fingerprint, EntryType::File)
        }),
    );
    fingerprints_by_expired_ago.extend(
      self
        .inner
        .directory_lmdb
        .clone()?
        .aged_fingerprints()
        .await?
        .into_iter()
        .map(|fingerprint| {
          used_bytes += fingerprint.size_bytes;
          (fingerprint, EntryType::Directory)
        }),
    );
    fingerprints_by_expired_ago.extend(
      self
        .inner
        .file_fsdb
        .aged_fingerprints()
        .await?
        .into_iter()
        .map(|fingerprint| {
          used_bytes += fingerprint.size_bytes;
          (fingerprint, EntryType::File)
        }),
    );

    while used_bytes > target_bytes {
      let (aged_fingerprint, entry_type) = fingerprints_by_expired_ago
        .pop()
        .expect("lmdb corruption detected, sum of size of blobs exceeded stored blobs");
      if aged_fingerprint.expired_seconds_ago == 0 {
        // Ran out of expired blobs - everything remaining is leased and cannot be collected.
        return Ok(used_bytes);
      }
      self
        .remove(
          entry_type,
          Digest {
            hash: aged_fingerprint.fingerprint,
            size_bytes: aged_fingerprint.size_bytes,
          },
        )
        .await?;
      used_bytes -= aged_fingerprint.size_bytes;
    }

    if shrink_behavior == ShrinkBehavior::Compact {
      self.inner.file_lmdb.clone()?.compact()?;
    }

    Ok(used_bytes)
  }

  pub async fn remove(&self, entry_type: EntryType, digest: Digest) -> Result<bool, String> {
    match entry_type {
      EntryType::Directory => self.inner.directory_lmdb.clone()?.remove(digest.hash).await,
      EntryType::File if ByteStore::should_use_fsdb(entry_type, digest.size_bytes) => {
        self.inner.file_fsdb.remove(digest.hash).await
      }
      EntryType::File => self.inner.file_lmdb.clone()?.remove(digest.hash).await,
    }
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
    self
      .store_bytes_batch(entry_type, vec![(fingerprint, bytes)], initial_lease)
      .await
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
    let mut fsdb_items = vec![];
    let mut lmdb_items = vec![];
    for (fingerprint, bytes) in items {
      if ByteStore::should_use_fsdb(entry_type, bytes.len()) {
        fsdb_items.push((fingerprint, bytes));
      } else {
        lmdb_items.push((fingerprint, bytes));
      }
    }

    let lmdb_dbs = match entry_type {
      EntryType::Directory => self.inner.directory_lmdb.clone(),
      EntryType::File => self.inner.file_lmdb.clone(),
    };
    try_join(
      self
        .inner
        .file_fsdb
        .store_bytes_batch(fsdb_items, initial_lease),
      lmdb_dbs?.store_bytes_batch(lmdb_items, initial_lease),
    )
    .await?;

    Ok(())
  }

  ///
  /// Store data in two passes, without buffering it entirely into memory. Prefer
  /// `Self::store_bytes` for small values which fit comfortably in memory.
  ///
  pub async fn store(
    &self,
    entry_type: EntryType,
    initial_lease: bool,
    src_is_immutable: bool,
    src: PathBuf,
  ) -> Result<Digest, String> {
    let digest = {
      let (mut file, _permit) = self
        .inner
        .file_source
        .open_readonly(&src)
        .await
        .map_err(|e| format!("Failed to open {src:?}: {e}"))?;
      async_copy_and_hash(&mut file, &mut tokio::io::sink())
        .await
        .map_err(|e| format!("Failed to hash {src:?}: {e}"))?
    };

    if ByteStore::should_use_fsdb(entry_type, digest.size_bytes) {
      self
        .inner
        .file_fsdb
        .store(
          initial_lease,
          src_is_immutable,
          digest,
          &self.inner.file_source,
          src,
        )
        .await?;
    } else {
      let dbs = match entry_type {
        EntryType::Directory => self.inner.directory_lmdb.clone()?,
        EntryType::File => self.inner.file_lmdb.clone()?,
      };
      let _ = dbs
        .store(initial_lease, src_is_immutable, digest, move || {
          // NB: This file access is bounded by the number of blocking threads on the runtime, and
          // so we don't bother to acquire against the file handle limit in this case.
          std::fs::File::open(&src)
        })
        .await;
    }

    Ok(digest)
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
    let mut fsdb_digests = vec![];
    let mut lmdb_digests = vec![];
    for digest in digests.iter() {
      if ByteStore::should_use_fsdb(entry_type, digest.size_bytes) {
        fsdb_digests.push(digest);
      }
      // Avoid I/O for this case. This allows some client-provided operations (like
      // merging snapshots) to work without needing to first store the empty snapshot.
      else if *digest != EMPTY_DIGEST {
        lmdb_digests.push(digest);
      }
    }

    let lmdb = match entry_type {
      EntryType::Directory => self.inner.directory_lmdb.clone(),
      EntryType::File => self.inner.file_lmdb.clone(),
    }?;
    let (mut existing, existing_lmdb_digests) = try_join(
      self
        .inner
        .file_fsdb
        .exists_batch(fsdb_digests.iter().map(|digest| digest.hash).collect()),
      lmdb.exists_batch(lmdb_digests.iter().map(|digest| digest.hash).collect()),
    )
    .await?;

    existing.extend(existing_lmdb_digests);

    Ok(
      digests
        .into_iter()
        .filter(|digest| *digest != EMPTY_DIGEST && !existing.contains(&digest.hash))
        .collect(),
    )
  }

  ///
  /// Return the path this digest is persistent on the filesystem at, or None.
  ///
  pub async fn load_from_fs(&self, digest: Digest) -> Result<Option<PathBuf>, String> {
    if self.inner.file_fsdb.exists(digest.hash).await? {
      return Ok(Some(self.inner.file_fsdb.get_path(digest.hash)));
    }
    Ok(None)
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

    let len_checked_f = move |bytes: &[u8]| {
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
    };

    let result = if ByteStore::should_use_fsdb(entry_type, digest.size_bytes) {
      self
        .inner
        .file_fsdb
        .load_bytes_with(digest.hash, len_checked_f)
        .await?
    } else {
      let dbs = match entry_type {
        EntryType::Directory => self.inner.directory_lmdb.clone(),
        EntryType::File => self.inner.file_lmdb.clone(),
      }?;
      dbs.load_bytes_with(digest.hash, len_checked_f).await?
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

    Ok(result)
  }

  pub async fn all_digests(&self, entry_type: EntryType) -> Result<Vec<Digest>, String> {
    let lmdb = match entry_type {
      EntryType::File => self.inner.file_lmdb.clone(),
      EntryType::Directory => self.inner.directory_lmdb.clone(),
    }?;
    let mut digests = vec![];
    digests.extend(lmdb.all_digests().await?);
    digests.extend(self.inner.file_fsdb.all_digests().await?);
    Ok(digests)
  }

  pub(crate) fn should_use_fsdb(entry_type: EntryType, len: usize) -> bool {
    entry_type == EntryType::File && len >= LARGE_FILE_SIZE_LIMIT
  }

  pub(crate) fn get_file_fsdb(&self) -> ShardedFSDB {
    self.inner.file_fsdb.clone()
  }
}
