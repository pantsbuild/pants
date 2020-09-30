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

use bytes::Bytes;
use hashing::{Fingerprint, FINGERPRINT_SIZE};
use lmdb::{
  self, Database, DatabaseFlags, Environment, EnvironmentCopyFlags, EnvironmentFlags,
  RwTransaction, Transaction, WriteFlags,
};
use log::trace;
use std::collections::HashMap;
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{self, Duration};
use tempfile::TempDir;

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
#[derive(Clone)]
pub struct ShardedLmdb {
  // First Database is content, second is leases.
  lmdbs: HashMap<u8, (Arc<Environment>, Database, Database)>,
  root_path: PathBuf,
  max_size: usize,
  executor: task_executor::Executor,
  lease_time: Duration,
}

impl ShardedLmdb {
  // Whenever we change the byte format of data stored in lmdb, we will
  // need to increment this schema version. This schema version will
  // be appended to the Fingerprint-derived keys to create the key
  // we actually store in the database. This way, data stored with a version
  // of pants on one schema version will not conflict with data stored
  // with a different version of pants on a different schema version.
  pub fn schema_version() -> u8 {
    1
  }

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
  ) -> Result<ShardedLmdb, String> {
    trace!("Initializing ShardedLmdb at root {:?}", root_path);
    let mut lmdbs = HashMap::new();

    for (env, dir, fingerprint_prefix) in ShardedLmdb::envs(&root_path, max_size)? {
      trace!("Making ShardedLmdb content database for {:?}", dir);
      let content_database = env
        .create_db(Some("content-versioned"), DatabaseFlags::empty())
        .map_err(|e| {
          format!(
            "Error creating/opening content database at {:?}: {}",
            dir, e
          )
        })?;

      trace!("Making ShardedLmdb lease database for {:?}", dir);
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
        (Arc::new(env), content_database, lease_database),
      );
    }

    Ok(ShardedLmdb {
      lmdbs,
      root_path,
      max_size,
      executor,
      lease_time,
    })
  }

  fn envs(root_path: &Path, max_size: usize) -> Result<Vec<(Environment, PathBuf, u8)>, String> {
    let mut envs = Vec::with_capacity(0x10);
    for b in 0x00..0x10 {
      let fingerprint_prefix = b << 4;
      let mut dirname = String::new();
      fmt::Write::write_fmt(&mut dirname, format_args!("{:x}", fingerprint_prefix)).unwrap();
      let dirname = dirname[0..1].to_owned();
      let dir = root_path.join(dirname);
      fs::safe_create_dir_all(&dir)
        .map_err(|err| format!("Error making directory for store at {:?}: {:?}", dir, err))?;
      envs.push((
        ShardedLmdb::make_env(&dir, max_size)?,
        dir,
        fingerprint_prefix,
      ));
    }
    Ok(envs)
  }

  fn make_env(dir: &Path, max_size: usize) -> Result<Environment, String> {
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
      .set_map_size(max_size)
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

  pub async fn remove(&self, fingerprint: Fingerprint) -> Result<bool, String> {
    let store = self.clone();
    self
      .executor
      .spawn_blocking(move || {
        let effective_key = VersionedFingerprint::new(fingerprint, ShardedLmdb::schema_version());
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
    let effective_key = VersionedFingerprint::new(fingerprint, ShardedLmdb::schema_version());
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
        let effective_key = VersionedFingerprint::new(fingerprint, ShardedLmdb::schema_version());
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
            &VersionedFingerprint::new(fingerprint, ShardedLmdb::schema_version()),
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
    F: Fn(&[u8]) -> Result<T, String> + Send + Sync + 'static,
  >(
    &self,
    fingerprint: Fingerprint,
    f: F,
  ) -> Result<Option<T>, String> {
    let store = self.clone();
    let effective_key = VersionedFingerprint::new(fingerprint, ShardedLmdb::schema_version());
    self
      .executor
      .spawn_blocking(move || {
        let (env, db, _) = store.get(&fingerprint);
        let ro_txn = env
          .begin_ro_txn()
          .map_err(|err| format!("Failed to begin read transaction: {}", err));
        ro_txn.and_then(|txn| match txn.get(db, &effective_key) {
          Ok(bytes) => f(bytes).map(Some),
          Err(lmdb::Error::NotFound) => Ok(None),
          Err(err) => Err(format!(
            "Error loading versioned key {:?}: {}",
            effective_key.to_hex(),
            err,
          )),
        })
      })
      .await
  }

  #[allow(clippy::identity_conversion)] // False positive: https://github.com/rust-lang/rust-clippy/issues/3913
  pub fn compact(&self) -> Result<(), String> {
    for (env, old_dir, _) in ShardedLmdb::envs(&self.root_path, self.max_size)? {
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
