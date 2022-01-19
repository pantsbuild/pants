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

use std::collections::HashMap;
use std::fmt;
use std::fmt::Debug;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{self, Duration};

use bytes::{BufMut, Bytes};
use hashing::{Digest, Fingerprint, WriterHasher, FINGERPRINT_SIZE};
use lmdb::{
  self, Database, DatabaseFlags, Environment, EnvironmentFlags, RwTransaction, Transaction,
  WriteFlags,
};
use log::trace;

///
/// The lease time is relatively short, because we in general would like things to be
/// garbage collectible. Leases are set on creation, and extended by pantsd for things that
/// are held in memory (since accessing the `Graph` will not extend leases on its own).
///
/// NB: This should align with the lease extension timeouts configured in the pantsd
/// StoreGCService.
///
pub const DEFAULT_LEASE_TIME: Duration = Duration::from_secs(2 * 60 * 60);

const VERSIONED_FINGERPRINT_SIZE: usize = FINGERPRINT_SIZE + 1;

/// VersionedFingerprint is a byte buffer one longer than the number of bytes stored in a
/// Fingerprint. It is just the byte pattern of a Fingerprint with the version number concatenated
/// onto the end of it.
pub struct VersionedFingerprint([u8; VERSIONED_FINGERPRINT_SIZE]);

impl VersionedFingerprint {
  pub fn new(fingerprint: Fingerprint, version: u8) -> VersionedFingerprint {
    let mut buf = [0; VERSIONED_FINGERPRINT_SIZE];
    buf[0..FINGERPRINT_SIZE].copy_from_slice(&fingerprint.0[..]);
    buf[FINGERPRINT_SIZE] = version;
    VersionedFingerprint(buf)
  }

  pub fn get_fingerprint(&self) -> Fingerprint {
    let mut buf = [0; FINGERPRINT_SIZE];
    buf.copy_from_slice(&self.0[0..FINGERPRINT_SIZE]);
    Fingerprint(buf)
  }

  pub fn from_bytes_unsafe(bytes: &[u8]) -> VersionedFingerprint {
    if bytes.len() != VERSIONED_FINGERPRINT_SIZE {
      panic!(
        "Input value was not a versioned fingerprint; had length: {}",
        bytes.len()
      );
    }

    let mut buf = [0; VERSIONED_FINGERPRINT_SIZE];
    buf.clone_from_slice(&bytes[0..VERSIONED_FINGERPRINT_SIZE]);
    VersionedFingerprint(buf)
  }

  pub fn to_hex(&self) -> String {
    let mut s = String::new();
    for byte in 0..VERSIONED_FINGERPRINT_SIZE {
      fmt::Write::write_fmt(&mut s, format_args!("{:02x}", byte)).unwrap();
    }
    s
  }
}

impl AsRef<[u8]> for VersionedFingerprint {
  fn as_ref(&self) -> &[u8] {
    &self.0[..]
  }
}

// Each LMDB directory can have at most one concurrent writer.
// We use this type to shard storage into 16 LMDB directories, based on the first 4 bits of the
// fingerprint being stored, so that we can write to them in parallel.
#[derive(Debug, Clone)]
pub struct ShardedLmdb {
  // First Database is content, second is leases.
  lmdbs: HashMap<u8, (PathBuf, Arc<Environment>, Database, Database)>,
  _root_path: PathBuf,
  _max_size_per_shard: usize,
  executor: task_executor::Executor,
  lease_time: Duration,
  _shard_count: u8,
  shard_fingerprint_mask: u8,
}

impl ShardedLmdb {
  // Whenever we change the byte format of data stored in lmdb, we will
  // need to increment this schema version. This schema version will
  // be appended to the Fingerprint-derived keys to create the key
  // we actually store in the database. This way, data stored with a version
  // of pants on one schema version will not conflict with data stored
  // with a different version of pants on a different schema version.
  pub const SCHEMA_VERSION: u8 = 2;

  // max_size is the maximum size the databases together will be allowed to grow to.
  // When calling this function, we will attempt to allocate that much virtual (not resident) memory
  // for the mmap; in theory it should be possible not to bound this, but in practice we see travis
  // occasionally fail tests because it's unable to allocate virtual memory if we set this too high,
  // and we have too many tests running concurrently or close together.
  pub fn new(
    root_path: PathBuf,
    max_size: usize,
    executor: task_executor::Executor,
    lease_time: Duration,
    shard_count: u8,
  ) -> Result<ShardedLmdb, String> {
    if shard_count.count_ones() != 1 {
      return Err(format!(
        "The shard_count must be a power of two: got {}.",
        shard_count
      ));
    }

    let max_size_per_shard = max_size / (shard_count as usize);
    // We select which shard to use by masking to select only the relevant number of high order bits
    // from the high order byte of each stored key.
    let shard_fingerprint_mask = {
      // Create a mask of the appropriate width.
      let mask_width = shard_count.trailing_zeros();
      let mut mask = 0_u8;
      for _ in 0..mask_width {
        mask <<= 1;
        mask |= 1;
      }
      // Then move it into the high order bits.
      mask.rotate_left(Self::shard_shift(shard_count) as u32)
    };

    trace!("Initializing ShardedLmdb at root {:?}", root_path);
    let mut lmdbs = HashMap::new();

    for (env, dir, fingerprint_prefix) in
      ShardedLmdb::envs(&root_path, max_size_per_shard, shard_count)?
    {
      let content_database = env
        .create_db(Some("content-versioned"), DatabaseFlags::empty())
        .map_err(|e| {
          format!(
            "Error creating/opening content database at {:?}: {}",
            dir, e
          )
        })?;

      let lease_database = env
        .create_db(Some("leases-versioned"), DatabaseFlags::empty())
        .map_err(|e| {
          format!(
            "Error creating/opening content database at {:?}: {}",
            dir, e
          )
        })?;

      lmdbs.insert(
        fingerprint_prefix,
        (dir, Arc::new(env), content_database, lease_database),
      );
    }

    Ok(ShardedLmdb {
      lmdbs,
      _root_path: root_path,
      _max_size_per_shard: max_size_per_shard,
      executor,
      lease_time,
      _shard_count: shard_count,
      shard_fingerprint_mask,
    })
  }

  ///
  /// Return the left shift value that will place the relevant portion of a byte (for the given
  /// shard count, which is asserted in the constructor to be a power of two) into the high order
  /// bits of a byte.
  ///
  fn shard_shift(shard_count: u8) -> u8 {
    let mask_width = shard_count.trailing_zeros() as u8;
    8 - mask_width
  }

  fn envs(
    root_path: &Path,
    max_size_per_shard: usize,
    shard_count: u8,
  ) -> Result<Vec<(Environment, PathBuf, u8)>, String> {
    let shard_shift = Self::shard_shift(shard_count);

    let mut envs = Vec::with_capacity(shard_count as usize);
    for b in 0..shard_count {
      let dir = root_path.join(format!("{:x}", b));
      fs::safe_create_dir_all(&dir)
        .map_err(|err| format!("Error making directory for store at {:?}: {:?}", dir, err))?;
      let fingerprint_prefix = b.rotate_left(shard_shift as u32);
      envs.push((
        ShardedLmdb::make_env(&dir, max_size_per_shard)?,
        dir,
        fingerprint_prefix,
      ));
    }
    Ok(envs)
  }

  fn make_env(dir: &Path, max_size_per_shard: usize) -> Result<Environment, String> {
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
      .set_map_size(max_size_per_shard)
      .open(dir)
      .map_err(|e| format!("Error making env for store at {:?}: {}", dir, e))
  }

  // First Database is content, second is leases.
  pub fn get(&self, fingerprint: &Fingerprint) -> (Arc<Environment>, Database, Database) {
    let (_, env, db1, db2) = self.get_raw(fingerprint.0[0]);
    (env.clone(), *db1, *db2)
  }

  pub(crate) fn get_raw(
    &self,
    prefix_byte: u8,
  ) -> &(PathBuf, Arc<Environment>, Database, Database) {
    &self.lmdbs[&(prefix_byte & self.shard_fingerprint_mask)]
  }

  pub fn all_lmdbs(&self) -> Vec<(Arc<Environment>, Database, Database)> {
    self
      .lmdbs
      .values()
      .map(|(_, env, db1, db2)| (env.clone(), *db1, *db2))
      .collect()
  }

  pub async fn remove(&self, fingerprint: Fingerprint) -> Result<bool, String> {
    let store = self.clone();
    self
      .executor
      .spawn_blocking(move || {
        let effective_key = VersionedFingerprint::new(fingerprint, ShardedLmdb::SCHEMA_VERSION);
        let (env, db, _lease_database) = store.get(&fingerprint);
        let del_res = env.begin_rw_txn().and_then(|mut txn| {
          txn.del(db, &effective_key, None)?;
          txn.commit()
        });

        match del_res {
          Ok(()) => Ok(true),
          Err(lmdb::Error::NotFound) => Ok(false),
          Err(err) => Err(format!(
            "Error removing versioned key {:?}: {}",
            effective_key.to_hex(),
            err
          )),
        }
      })
      .await
  }

  pub async fn exists(&self, fingerprint: Fingerprint) -> Result<bool, String> {
    let store = self.clone();
    let effective_key = VersionedFingerprint::new(fingerprint, ShardedLmdb::SCHEMA_VERSION);
    self
      .executor
      .spawn_blocking(move || {
        let fingerprint = effective_key.get_fingerprint();
        let (env, db, _) = store.get(&fingerprint);
        let txn = env
          .begin_ro_txn()
          .map_err(|err| format!("Failed to begin read transaction: {:?}", err))?;
        match txn.get(db, &effective_key) {
          Ok(_) => Ok(true),
          Err(lmdb::Error::NotFound) => Ok(false),
          Err(err) => Err(format!(
            "Error reading from store when checking existence of {}: {}",
            fingerprint, err
          )),
        }
      })
      .await
  }

  pub async fn store_bytes(
    &self,
    fingerprint: Fingerprint,
    bytes: Bytes,
    initial_lease: bool,
  ) -> Result<(), String> {
    let store = self.clone();
    self
      .executor
      .spawn_blocking(move || {
        let effective_key = VersionedFingerprint::new(fingerprint, ShardedLmdb::SCHEMA_VERSION);
        let (env, db, lease_database) = store.get(&fingerprint);
        let put_res = env.begin_rw_txn().and_then(|mut txn| {
          txn.put(db, &effective_key, &bytes, WriteFlags::NO_OVERWRITE)?;
          if initial_lease {
            store.lease_inner(
              lease_database,
              &effective_key,
              store.lease_until_secs_since_epoch(),
              &mut txn,
            )?;
          }
          txn.commit()
        });

        match put_res {
          Ok(()) => Ok(()),
          Err(lmdb::Error::KeyExist) => Ok(()),
          Err(err) => Err(format!(
            "Error storing versioned key {:?}: {}",
            effective_key.to_hex(),
            err
          )),
        }
      })
      .await
  }

  ///
  /// Stores the given Read instance under its computed digest. This method performs two passes
  /// over the source to 1) hash it, 2) store it. If !data_is_immutable, the second pass will
  /// re-hash the data to confirm that it hasn't changed.
  ///
  /// If the Read instance gets longer between Reads, we will not detect that here, but any
  /// captured data will still be valid.
  ///
  pub async fn store<F, R>(
    &self,
    initial_lease: bool,
    data_is_immutable: bool,
    data_provider: F,
  ) -> Result<Digest, String>
  where
    R: Read + Debug,
    F: Fn() -> Result<R, io::Error> + Send + 'static,
  {
    let store = self.clone();
    self
      .executor
      .spawn_blocking(move || {
        let mut attempts = 0;
        loop {
          // First pass: compute the Digest.
          let digest = {
            let mut read = data_provider().map_err(|e| format!("Failed to read: {}", e))?;
            let mut hasher = WriterHasher::new(io::sink());
            let _ = io::copy(&mut read, &mut hasher)
              .map_err(|e| format!("Failed to read from {:?}: {}", read, e))?;
            hasher.finish().0
          };

          let effective_key = VersionedFingerprint::new(digest.hash, ShardedLmdb::SCHEMA_VERSION);
          let (env, db, lease_database) = store.get(&digest.hash);
          let put_res: Result<(), StoreError> = env
            .begin_rw_txn()
            .map_err(StoreError::Lmdb)
            .and_then(|mut txn| {
              // Second pass: copy into the reserved memory.
              let mut writer = txn
                .reserve(
                  db,
                  &effective_key,
                  digest.size_bytes,
                  WriteFlags::NO_OVERWRITE,
                )?
                .writer();
              let mut read = data_provider().map_err(|e| format!("Failed to read: {}", e))?;
              let should_retry = if data_is_immutable {
                // Trust that the data hasn't changed, and only validate its length.
                let copied = io::copy(&mut read, &mut writer).map_err(|e| {
                  format!(
                    "Failed to copy from {:?} or store in {:?}: {:?}",
                    read, env, e
                  )
                })?;

                // Should retry if the file got shorter between reads.
                copied as usize != digest.size_bytes
              } else {
                // Confirm that the data hasn't changed.
                let mut hasher = WriterHasher::new(writer);
                let _ = io::copy(&mut read, &mut hasher).map_err(|e| {
                  format!(
                    "Failed to copy from {:?} or store in {:?}: {:?}",
                    read, env, e
                  )
                })?;

                // Should retry if the Digest changed between reads.
                digest != hasher.finish().0
              };

              if should_retry {
                let msg = format!("Input {:?} changed while reading.", read);
                log::debug!("{}", msg);
                return Err(StoreError::Retry(msg));
              }

              if initial_lease {
                store.lease_inner(
                  lease_database,
                  &effective_key,
                  store.lease_until_secs_since_epoch(),
                  &mut txn,
                )?;
              }
              txn.commit()?;
              Ok(())
            });

          match put_res {
            Ok(()) => return Ok(digest),
            Err(StoreError::Retry(msg)) => {
              // Input changed during reading: maybe retry.
              if attempts > 10 {
                return Err(msg);
              } else {
                attempts += 1;
                continue;
              }
            }
            Err(StoreError::Lmdb(lmdb::Error::KeyExist)) => return Ok(digest),
            Err(StoreError::Lmdb(err)) => {
              return Err(format!("Error storing {:?}: {}", digest, err))
            }
            Err(StoreError::Io(err)) => return Err(format!("Error storing {:?}: {}", digest, err)),
          };
        }
      })
      .await
  }

  pub async fn lease(&self, fingerprint: Fingerprint) -> Result<(), lmdb::Error> {
    let store = self.clone();
    self
      .executor
      .spawn_blocking(move || {
        let until_secs_since_epoch: u64 = store.lease_until_secs_since_epoch();
        let (env, _, lease_database) = store.get(&fingerprint);
        env.begin_rw_txn().and_then(|mut txn| {
          store.lease_inner(
            lease_database,
            &VersionedFingerprint::new(fingerprint, ShardedLmdb::SCHEMA_VERSION),
            until_secs_since_epoch,
            &mut txn,
          )?;
          txn.commit()
        })
      })
      .await
  }

  fn lease_inner(
    &self,
    database: Database,
    versioned_fingerprint: &VersionedFingerprint,
    until_secs_since_epoch: u64,
    txn: &mut RwTransaction<'_>,
  ) -> Result<(), lmdb::Error> {
    txn.put(
      database,
      &versioned_fingerprint.as_ref(),
      &until_secs_since_epoch.to_le_bytes(),
      WriteFlags::empty(),
    )
  }

  fn lease_until_secs_since_epoch(&self) -> u64 {
    let now_since_epoch = time::SystemTime::now()
      .duration_since(time::UNIX_EPOCH)
      .expect("Surely you're not before the unix epoch?");
    (now_since_epoch + self.lease_time).as_secs()
  }

  pub async fn load_bytes_with<
    T: Send + 'static,
    F: FnMut(&[u8]) -> Result<T, String> + Send + Sync + 'static,
  >(
    &self,
    fingerprint: Fingerprint,
    mut f: F,
  ) -> Result<Option<T>, String> {
    let store = self.clone();
    let effective_key = VersionedFingerprint::new(fingerprint, ShardedLmdb::SCHEMA_VERSION);
    self
      .executor
      .spawn_blocking(move || {
        let (env, db, _) = store.get(&fingerprint);
        let ro_txn = env
          .begin_ro_txn()
          .map_err(|err| format!("Failed to begin read transaction: {}", err))?;
        match ro_txn.get(db, &effective_key) {
          Ok(bytes) => f(bytes).map(Some),
          Err(lmdb::Error::NotFound) => Ok(None),
          Err(err) => Err(format!(
            "Error loading versioned key {:?}: {}",
            effective_key.to_hex(),
            err,
          )),
        }
      })
      .await
  }
}

enum StoreError {
  Lmdb(lmdb::Error),
  Io(String),
  Retry(String),
}

impl From<lmdb::Error> for StoreError {
  fn from(err: lmdb::Error) -> Self {
    Self::Lmdb(err)
  }
}

impl From<String> for StoreError {
  fn from(err: String) -> Self {
    Self::Io(err)
  }
}

#[cfg(test)]
mod tests;
