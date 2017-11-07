use bazel_protos;
use digest::{Digest, FixedOutput};
use lmdb::{Database, DatabaseFlags, Environment, NO_OVERWRITE, Transaction};
use lmdb::Error::{KeyExist, NotFound};
use protobuf::core::Message;
use sha2::Sha256;
use std::error::Error;
use std::path::Path;

use hash::Fingerprint;

///
/// A content-addressed store of file contents, and Directories.
///
/// Currently, Store only stores things locally on disk, but in the future it will gain the ability
/// to fetch files from remote content-addressable storage too.
///
pub struct Store {
  env: Environment,
  file_store: Database,

  // Store directories separately from files because:
  //  1. They may have different lifetimes.
  //  2. It's nice to know whether we should be able to parse something as a proto.
  directory_store: Database,
}

impl Store {
  pub fn new<P: AsRef<Path>>(path: P) -> Result<Store, String> {
    // 2 DBs; one for file contents, one for directories.
    let env = Environment::new()
      .set_max_dbs(2)
      .set_map_size(16 * 1024 * 1024 * 1024)
      .open(path.as_ref())
      .map_err(|e| format!("Error making env: {}", e.description()))?;
    let file_database = env
      .create_db(Some("files"), DatabaseFlags::empty())
      .map_err(|e| {
        format!("Error creating/opening files database: {}", e.description())
      })?;
    let directory_database = env
      .create_db(Some("directories"), DatabaseFlags::empty())
      .map_err(|e| {
        format!(
          "Error creating/opening directories database: {}",
          e.description()
        )
      })?;
    Ok(Store {
      env: env,
      file_store: file_database,
      directory_store: directory_database,
    })
  }

  pub fn store_file_bytes(&self, bytes: &[u8]) -> Result<Fingerprint, String> {
    self.store_bytes(bytes, self.file_store.clone())
  }

  fn store_bytes(&self, bytes: &[u8], db: Database) -> Result<Fingerprint, String> {
    let mut hasher = Sha256::default();
    hasher.input(&bytes);
    let fingerprint = Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice());

    match self.env.begin_rw_txn().and_then(|mut txn| {
      txn.put(db, &fingerprint, &bytes, NO_OVERWRITE).and_then(
        |()| txn.commit(),
      )
    }) {
      Ok(()) => Ok(fingerprint),
      Err(KeyExist) => Ok(fingerprint),
      Err(err) => Err(format!(
        "Error storing fingerprint {}: {}",
        fingerprint,
        err.description()
      )),
    }
  }

  pub fn load_file_bytes(&self, fingerprint: &Fingerprint) -> Result<Option<Vec<u8>>, String> {
    self.load_bytes(fingerprint, self.file_store.clone())
  }

  pub fn load_directory_proto_bytes(
    &self,
    fingerprint: &Fingerprint,
  ) -> Result<Option<Vec<u8>>, String> {
    self.load_bytes(fingerprint, self.directory_store.clone())
  }

  pub fn load_bytes(
    &self,
    fingerprint: &Fingerprint,
    db: Database,
  ) -> Result<Option<Vec<u8>>, String> {
    match self.env.begin_ro_txn().and_then(|txn| {
      txn.get(db, fingerprint).map(|v| v.to_vec())
    }) {
      Ok(v) => Ok(Some(v)),
      Err(NotFound) => Ok(None),
      Err(err) => Err(format!(
        "Error loading fingerprint {}: {}",
        fingerprint,
        err.description().to_string()
      )),
    }
  }

  ///
  /// Store the Directory proto. Does not do anything about the files or directories claimed to be
  /// contained therein.
  ///
  /// Assumes that the directory has been properly canonicalized.
  ///
  pub fn record_directory(
    &self,
    directory: &bazel_protos::remote_execution::Directory,
  ) -> Result<(Fingerprint, usize), String> {
    let bytes = directory.write_to_bytes().map_err(|e| {
      format!(
        "Error serializing directory proto {:?}: {}",
        directory,
        e.description()
      )
    })?;

    Ok((
      self.store_bytes(&bytes, self.directory_store.clone())?,
      bytes.len(),
    ))
  }
}

#[cfg(test)]
mod tests {
  extern crate tempdir;

  use bazel_protos;
  use super::{Fingerprint, Store};
  use lmdb::{DatabaseFlags, Environment, Transaction, WriteFlags};
  use tempdir::TempDir;


  const STR: &str = "European Burmese";
  const HASH: &str = "693d8db7b05e99c6b7a7c0616456039d89c555029026936248085193559a0b5d";

  #[test]
  fn save_file() {
    let dir = TempDir::new("store").unwrap();

    assert_eq!(
      &Store::new(dir.path())
        .unwrap()
        .store_file_bytes(STR.as_bytes())
        .unwrap()
        .to_hex(),
      HASH
    );
  }

  #[test]
  fn save_file_is_idempotent() {
    let dir = TempDir::new("store").unwrap();

    &Store::new(dir.path())
      .unwrap()
      .store_file_bytes(STR.as_bytes())
      .unwrap();
    assert_eq!(
      &Store::new(dir.path())
        .unwrap()
        .store_file_bytes(STR.as_bytes())
        .unwrap()
        .to_hex(),
      HASH
    );
  }

  #[test]
  fn save_file_collision_preserves_first() {
    let dir = TempDir::new("store").unwrap();

    let fingerprint = Fingerprint::from_hex_string(HASH).unwrap();
    let bogus_value: &[u8] = &[][..];

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
      Store::new(dir.path())
        .unwrap()
        .load_file_bytes(&fingerprint)
        .unwrap()
        .unwrap(),
      bogus_value
    );

    assert_eq!(
      &Store::new(dir.path())
        .unwrap()
        .store_file_bytes(STR.as_bytes())
        .unwrap()
        .to_hex(),
      HASH
    );

    assert_eq!(
      &Store::new(dir.path())
        .unwrap()
        .load_file_bytes(&fingerprint)
        .unwrap()
        .unwrap(),
      &Vec::from(bogus_value)
    );
  }

  #[test]
  fn roundtrip_file() {
    let data = Vec::from(STR.as_bytes());
    let dir = TempDir::new("store").unwrap();

    let store = Store::new(dir.path()).unwrap();
    let hash = store.store_file_bytes(&data).unwrap();
    assert_eq!(store.load_file_bytes(&hash).unwrap().unwrap(), data);
  }

  #[test]
  fn missing_file() {
    let dir = TempDir::new("store").unwrap();
    assert_eq!(
      Store::new(dir.path())
        .unwrap()
        .load_file_bytes(&Fingerprint::from_hex_string(HASH).unwrap())
        .unwrap(),
      None
    );
  }

  #[test]
  fn record_directory_proto() {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("roland".to_string());
      file.set_digest({
        let mut digest = bazel_protos::remote_execution::Digest::new();
        digest.set_hash(HASH.to_string());
        digest.set_size_bytes(STR.len() as i64);
        digest
      });
      file.set_is_executable(false);
      file
    });

    let dir = TempDir::new("store").unwrap();

    assert_eq!(
      &Store::new(dir.path())
        .unwrap()
        .record_directory(&directory)
        .unwrap()
        .0
        .to_hex(),
      "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16"
    );
  }
}
