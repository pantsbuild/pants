use bazel_protos;
use digest::{Digest as DigestTrait, FixedOutput};
use lmdb::{Database, DatabaseFlags, Environment, NO_OVERWRITE, Transaction};
use lmdb::Error::{KeyExist, NotFound};
use protobuf::core::Message;
use sha2::Sha256;
use std::error::Error;
use std::path::Path;
use std::sync::Arc;

use hash::Fingerprint;

///
/// A content-addressed store of file contents, and Directories.
///
/// Currently, Store only stores things locally on disk, but in the future it will gain the ability
/// to fetch files from remote content-addressable storage too.
///
#[derive(Clone)]
pub struct Store {
  inner: Arc<InnerStore>,
}

struct InnerStore {
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
      inner: Arc::new(InnerStore {
        env: env,
        file_store: file_database,
        directory_store: directory_database,
      }),
    })
  }

  pub fn store_file_bytes(&self, bytes: &[u8]) -> Result<Digest, String> {
    self.store_bytes(bytes, self.inner.file_store.clone()).map(
      |fingerprint| Digest(fingerprint, bytes.len()),
    )
  }

  fn store_bytes(&self, bytes: &[u8], db: Database) -> Result<Fingerprint, String> {
    let mut hasher = Sha256::default();
    hasher.input(&bytes);
    let fingerprint = Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice());

    match self.inner.env.begin_rw_txn().and_then(|mut txn| {
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
    self.load_bytes(fingerprint, self.inner.file_store.clone())
  }

  pub fn load_directory_proto_bytes(
    &self,
    fingerprint: &Fingerprint,
  ) -> Result<Option<Vec<u8>>, String> {
    self.load_bytes(fingerprint, self.inner.directory_store.clone())
  }

  pub fn load_directory_proto(
    &self,
    fingerprint: &Fingerprint,
  ) -> Result<Option<bazel_protos::remote_execution::Directory>, String> {
    match self.load_directory_proto_bytes(fingerprint)? {
      Some(bytes) => {
        let mut proto = bazel_protos::remote_execution::Directory::new();
        proto.merge_from_bytes(&bytes).map_err(|e| {
          format!("Error deserializing proto {}: {}", fingerprint, e)
        })?;
        Ok(Some(proto))
      }
      None => Ok(None),
    }
  }

  pub fn load_bytes(
    &self,
    fingerprint: &Fingerprint,
    db: Database,
  ) -> Result<Option<Vec<u8>>, String> {
    match self.inner.env.begin_ro_txn().and_then(|txn| {
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
  ) -> Result<Digest, String> {
    let bytes = directory.write_to_bytes().map_err(|e| {
      format!(
        "Error serializing directory proto {:?}: {}",
        directory,
        e.description()
      )
    })?;

    Ok(Digest(
      self.store_bytes(&bytes, self.inner.directory_store.clone())?,
      bytes.len(),
    ))
  }
}

///
/// A Digest is a fingerprint, as well as the size in bytes of the plaintext for which that is the
/// fingerprint.
///
/// It is equivalent to a Bazel Remote Execution Digest, but without the overhead (and awkward API)
/// of needing to create an entire protobuf to pass around the two fields.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Digest(pub Fingerprint, pub usize);

impl Into<bazel_protos::remote_execution::Digest> for Digest {
  fn into(self) -> bazel_protos::remote_execution::Digest {
    let mut digest = bazel_protos::remote_execution::Digest::new();
    digest.set_hash(self.0.to_hex());
    digest.set_size_bytes(self.1 as i64);
    digest
  }
}

#[cfg(test)]
mod tests {
  extern crate tempdir;

  use bazel_protos;
  use super::{Digest, Fingerprint, Store};
  use lmdb::{DatabaseFlags, Environment, Transaction, WriteFlags};
  use protobuf::Message;
  use tempdir::TempDir;


  const STR: &str = "European Burmese";
  const HASH: &str = "693d8db7b05e99c6b7a7c0616456039d89c555029026936248085193559a0b5d";

  fn digest() -> Digest {
    Digest(Fingerprint::from_hex_string(HASH).unwrap(), STR.len())
  }

  #[test]
  fn save_file() {
    let dir = TempDir::new("store").unwrap();

    assert_eq!(
      Store::new(dir.path())
        .unwrap()
        .store_file_bytes(STR.as_bytes())
        .unwrap(),
      digest()
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
      Store::new(dir.path())
        .unwrap()
        .store_file_bytes(STR.as_bytes())
        .unwrap(),
      digest()
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
      Store::new(dir.path())
        .unwrap()
        .store_file_bytes(STR.as_bytes())
        .unwrap(),
      digest()
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
    assert_eq!(store.load_file_bytes(&hash.0).unwrap().unwrap(), data);
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
  fn record_and_load_directory_proto() {
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

    let hash = "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16";

    assert_eq!(
      &Store::new(dir.path())
        .unwrap()
        .record_directory(&directory)
        .unwrap()
        .0
        .to_hex(),
      hash
    );

    assert_eq!(
      Store::new(dir.path())
        .unwrap()
        .load_directory_proto(&Fingerprint::from_hex_string(hash).unwrap())
        .unwrap()
        .unwrap(),
      directory
    );

    assert_eq!(
      Store::new(dir.path())
        .unwrap()
        .load_directory_proto_bytes(&Fingerprint::from_hex_string(hash).unwrap())
        .unwrap()
        .unwrap(),
      directory.write_to_bytes().unwrap()
    );
  }

  #[test]
  fn file_is_not_directory_proto() {
    let dir = TempDir::new("store").unwrap();

    Store::new(dir.path())
      .unwrap()
      .store_file_bytes(STR.as_bytes())
      .unwrap();

    assert_eq!(
      Store::new(dir.path())
        .unwrap()
        .load_directory_proto(&Fingerprint::from_hex_string(HASH).unwrap())
        .unwrap(),
      None
    );

    assert_eq!(
      Store::new(dir.path())
        .unwrap()
        .load_directory_proto_bytes(&Fingerprint::from_hex_string(HASH).unwrap())
        .unwrap(),
      None
    );
  }

  #[test]
  fn digest_to_bazel_digest() {
    let digest = Digest(Fingerprint::from_hex_string(HASH).unwrap(), 16);
    let mut bazel_digest = bazel_protos::remote_execution::Digest::new();
    bazel_digest.set_hash(HASH.to_string());
    bazel_digest.set_size_bytes(16);
    assert_eq!(bazel_digest, digest.into());
  }
}
