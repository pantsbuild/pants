use bazel_protos;
use digest::{Digest, FixedOutput};
use lmdb_rs::{DbFlags, DbHandle, EnvBuilder, Environment, MdbError, MdbValue, ToMdbValue};
use protobuf::core::Message;
use sha2::Sha256;
use std::error::Error;
use std::mem::transmute;
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
  file_store: DbHandle,

  // Store directories separately from files because:
  //  1. They may have different lifetimes.
  //  2. It's nice to know whether we should be able to parse something as a proto.
  directory_store: DbHandle,
}

impl Store {
  pub fn new<P: AsRef<Path>>(path: P) -> Result<Store, String> {
    // 2 DBs; one for file contents, one for directories.
    let env = EnvBuilder::new().max_dbs(2).open(path, 0o600).map_err(
      |e| {
        format!("Error making env: {}", e.description())
      },
    )?;
    let file_db_handle = env.create_db("files", DbFlags::empty()).map_err(|e| {
      format!("Error creating/opening files database: {}", e.description())
    })?;
    let directory_db_handle = env.create_db("directories", DbFlags::empty()).map_err(
      |e| {
        format!(
          "Error creating/opening directories database: {}",
          e.description()
        )
      },
    )?;
    Ok(Store {
      env: env,
      file_store: file_db_handle,
      directory_store: directory_db_handle,
    })
  }

  pub fn store_file_bytes(&self, bytes: &[u8]) -> Result<Fingerprint, String> {
    self.store_bytes(bytes, &self.file_store)
  }

  fn store_bytes(&self, bytes: &[u8], db: &DbHandle) -> Result<Fingerprint, String> {
    let mut hasher = Sha256::default();
    hasher.input(&bytes);
    let fingerprint = Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice());

    let txn = self.env.new_transaction().map_err(|e| {
      format!(
        "Error making new transaction to store fingerprint {}: {}",
        fingerprint,
        e.description()
      )
    })?;
    {
      let db = txn.bind(db);
      match db.insert(&fingerprint, &bytes) {
        Ok(_) => {}
        Err(MdbError::KeyExists) => return Ok(fingerprint),
        Err(err) => {
          return Err(format!(
            "Error storing fingerprint {}: {}",
            fingerprint,
            err.description()
          ))
        }
      };
    }
    match txn.commit() {
      Ok(_) => Ok(fingerprint),
      Err(MdbError::KeyExists) => Ok(fingerprint),
      Err(err) => Err(format!(
        "Error committing transaction for fingerprint {}: {}",
        fingerprint,
        err.description()
      )),
    }
  }

  pub fn load_bytes(&self, fingerprint: &Fingerprint) -> Result<Option<Vec<u8>>, String> {
    let reader = self.env.get_reader().map_err(|e| {
      format!(
        "Error getting reader for fingerprint {}: {}",
        fingerprint,
        e.description()
      )
    })?;
    let db = reader.bind(&self.file_store);
    match db.get(&fingerprint.as_bytes().as_ref()) {
      Ok(v) => Ok(Some(v)),
      Err(MdbError::NotFound) => Ok(None),
      Err(err) => Err(format!(
        "Error getting fingerprint {}: {}",
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
      self.store_bytes(&bytes, &self.directory_store)?,
      bytes.len(),
    ))
  }
}

impl ToMdbValue for Fingerprint {
  fn to_mdb_value<'a>(&'a self) -> MdbValue<'a> {
    unsafe { MdbValue::new(transmute(self.as_bytes().as_ptr()), self.as_bytes().len()) }
  }
}

#[cfg(test)]
mod tests {
  use bazel_protos;
  use super::{Fingerprint, Store};
  extern crate tempdir;
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
  fn roundtrip_file() {
    let data = Vec::from(STR.as_bytes());
    let dir = TempDir::new("store").unwrap();

    let store = Store::new(dir.path()).unwrap();
    let hash = store.store_file_bytes(&data).unwrap();
    assert_eq!(store.load_bytes(&hash).unwrap().unwrap(), data);
  }

  #[test]
  fn missing_file() {
    let dir = TempDir::new("store").unwrap();
    assert_eq!(
      Store::new(dir.path())
        .unwrap()
        .load_bytes(&Fingerprint::from_hex_string(HASH).unwrap())
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
