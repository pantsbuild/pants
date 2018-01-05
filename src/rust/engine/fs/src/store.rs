use bazel_protos;
use boxfuture::{BoxFuture, Boxable};
use futures::{Future, future};
use protobuf::core::Message;
use std::path::Path;
use std::sync::Arc;

use hash::Fingerprint;
use pool::ResettablePool;

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

///
/// A content-addressed store of file contents, and Directories.
///
/// Store keeps content on disk, and can optionally delegate to backfill its on-disk storage by
/// fetching files from a remote server which implements the gRPC bytestream interface
/// (see https://github.com/googleapis/googleapis/blob/master/google/bytestream/bytestream.proto)
/// as specified by the gRPC remote execution interface (see
/// https://github.com/googleapis/googleapis/blob/master/google/devtools/remoteexecution/v1test/)
///
/// In the future, it will gain the ability to write back to the gRPC server, too.
///
#[derive(Clone)]
pub struct Store {
  local: local::ByteStore,
  remote: Option<remote::ByteStore>,
}

// Note that Store doesn't implement ByteStore because it operates at a higher level of abstraction,
// considering Directories as a standalone concept, rather than a buffer of bytes.
// This has the nice property that Directories can be trusted to be valid and canonical.
// We may want to re-visit this if we end up wanting to handle local/remote/merged interchangably.
impl Store {
  ///
  /// Make a store which only uses its local storage.
  ///
  pub fn local_only<P: AsRef<Path>>(path: P, pool: Arc<ResettablePool>) -> Result<Store, String> {
    Ok(Store {
      local: local::ByteStore::new(path, pool)?,
      remote: None,
    })
  }

  ///
  /// Make a store which uses local storage, and if it is missing a value which it tries to load,
  /// will attempt to back-fill its local storage from a remote CAS.
  ///
  pub fn backfills_from_remote<P: AsRef<Path>>(
    path: P,
    pool: Arc<ResettablePool>,
    cas_address: String,
  ) -> Result<Store, String> {
    Ok(Store {
      local: local::ByteStore::new(path, pool)?,
      remote: Some(remote::ByteStore::new(cas_address)),
    })
  }

  pub fn store_file_bytes(&self, bytes: Vec<u8>) -> BoxFuture<Digest, String> {
    self.local.store_bytes(EntryType::File, bytes)
  }

  ///
  /// Loads the bytes of the file with the passed fingerprint, and returns the result of applying f
  /// to that value.
  ///
  pub fn load_file_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
    &self,
    fingerprint: Fingerprint,
    f: F,
  ) -> BoxFuture<Option<T>, String> {
    // No transformation or verification is needed for files, so we pass in a pair of functions
    // which always succeed, whether the underlying bytes are coming from a local or remote store.
    // Unfortunately, we need to be a little verbose to do this.
    let f_local = Arc::new(f);
    let f_remote = f_local.clone();
    self.load_bytes_with(
      EntryType::File,
      fingerprint,
      move |v: &[u8]| Ok(f_local(v)),
      move |v: &[u8]| Ok(f_remote(v)),
    )
  }

  ///
  /// Save the bytes of the Directory proto, without regard for any of the contents of any FileNodes
  /// or DirectoryNodes therein (i.e. does not require that its children are already stored).
  ///
  pub fn record_directory(
    &self,
    directory: &bazel_protos::remote_execution::Directory,
  ) -> BoxFuture<Digest, String> {
    let local = self.local.clone();
    future::result(directory.write_to_bytes().map_err(|e| {
      format!("Error serializing directory proto {:?}: {:?}", directory, e)
    })).and_then(move |bytes| local.store_bytes(EntryType::Directory, bytes))
      .to_boxed()
  }

  ///
  /// Guarantees that if an Ok Some value is returned, it is valid, and canonical, and its
  /// fingerprint exactly matches that which is requested. Will return an Err if it would return a
  /// non-canonical Directory.
  ///
  pub fn load_directory(
    &self,
    fingerprint: Fingerprint,
  ) -> BoxFuture<Option<bazel_protos::remote_execution::Directory>, String> {
    let fingerprint_copy = fingerprint.clone();
    let fingerprint_copy2 = fingerprint.clone();
    self.load_bytes_with(
      EntryType::Directory,
      fingerprint.clone(),
      // Trust that locally stored values were canonical when they were written into the CAS,
      // don't bother to check this, as it's slightly expensive.
      move |bytes: &[u8]| {
        let mut directory = bazel_protos::remote_execution::Directory::new();
        directory.merge_from_bytes(bytes).map_err(|e| {
          format!(
            "LMDB corruption: Directory bytes for {} were not valid: {:?}",
            fingerprint_copy,
            e
          )
        })?;
        Ok(directory)
      },
      // Eagerly verify that CAS-returned Directories are canonical, so that we don't write them
      // into our local store.
      move |bytes: &[u8]| {
        let mut directory = bazel_protos::remote_execution::Directory::new();
        directory.merge_from_bytes(bytes).map_err(|e| {
          format!(
            "CAS returned Directory proto for {} which was not valid: {:?}",
            fingerprint_copy2,
            e
          )
        })?;
        bazel_protos::verify_directory_canonical(&directory)?;
        Ok(directory)
      },
    )
  }

  fn load_bytes_with<
    T: Send + 'static,
    FLocal: Fn(&[u8]) -> Result<T, String> + Send + Sync + 'static,
    FRemote: Fn(&[u8]) -> Result<T, String> + Send + Sync + 'static,
  >(
    &self,
    entry_type: EntryType,
    fingerprint: Fingerprint,
    f_local: FLocal,
    f_remote: FRemote,
  ) -> BoxFuture<Option<T>, String> {
    let local = self.local.clone();
    let maybe_remote = self.remote.clone();
    self
      .local
      .load_bytes_with(entry_type, fingerprint.clone(), f_local)
      .and_then(move |maybe_local_value| match (
        maybe_local_value,
        maybe_remote,
      ) {
        (Some(value_result), _) => {
          future::done(value_result.map(|v| Some(v))).to_boxed() as BoxFuture<_, _>
        }
        (None, None) => future::ok(None).to_boxed() as BoxFuture<_, _>,
        (None, Some(remote)) => {
          remote
            .load_bytes_with(
              entry_type,
              fingerprint,
              move |bytes: &[u8]| Vec::from(bytes),
            )
            .and_then(move |maybe_bytes: Option<Vec<u8>>| match maybe_bytes {
              Some(bytes) => {
                future::done(f_remote(&bytes))
                  .and_then(move |value| {
                    local.store_bytes(entry_type, bytes).and_then(
                      move |digest| if digest.0 ==
                        fingerprint
                      {
                        Ok(Some(value))
                      } else {
                        Err(format!(
                          "CAS gave wrong fingerprint: expected {}, got {}",
                          fingerprint,
                          digest.0
                        ))
                      },
                    )
                  })
                  .to_boxed()
              }
              None => future::ok(None).to_boxed() as BoxFuture<_, _>,
            })
            .to_boxed()
        }
      })
      .to_boxed()
  }
}

// Only public for testing.
#[derive(Copy, Clone)]
pub enum EntryType {
  Directory,
  File,
}

///
/// ByteStore allows read and write access to byte-buffers of two types:
/// 1. File contents (arbitrary blobs with no particular assumed structure).
/// 2. Directory protos, serialized using the standard protobuf binary serialization.
///
pub trait ByteStore {
  fn store_bytes(&self, entry_type: EntryType, bytes: Vec<u8>) -> BoxFuture<Digest, String>;

  fn load_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
    &self,
    entry_type: EntryType,
    fingerprint: Fingerprint,
    f: F,
  ) -> BoxFuture<Option<T>, String>;
}

mod local {
  use super::{Digest, EntryType};

  use boxfuture::{Boxable, BoxFuture};
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::Future;
  use lmdb::{Database, DatabaseFlags, Environment, NO_OVERWRITE, Transaction};
  use lmdb::Error::{KeyExist, NotFound};
  use sha2::Sha256;
  use std::error::Error;
  use std::path::Path;
  use std::sync::Arc;

  use hash::Fingerprint;
  use pool::ResettablePool;

  #[derive(Clone)]
  pub struct ByteStore {
    inner: Arc<InnerStore>,
  }

  struct InnerStore {
    env: Environment,
    pool: Arc<ResettablePool>,
    file_store: Database,
    // Store directories separately from files because:
    //  1. They may have different lifetimes.
    //  2. It's nice to know whether we should be able to parse something as a proto.
    directory_store: Database,
  }

  impl ByteStore {
    pub fn new<P: AsRef<Path>>(path: P, pool: Arc<ResettablePool>) -> Result<ByteStore, String> {
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
      Ok(ByteStore {
        inner: Arc::new(InnerStore {
          env: env,
          pool: pool,
          file_store: file_database,
          directory_store: directory_database,
        }),
      })
    }
  }

  impl super::ByteStore for ByteStore {
    fn store_bytes(&self, entry_type: EntryType, bytes: Vec<u8>) -> BoxFuture<Digest, String> {
      let len = bytes.len();
      let db = match entry_type {
        EntryType::Directory => self.inner.directory_store,
        EntryType::File => self.inner.file_store,
      }.clone();

      let inner = self.inner.clone();
      self
        .inner
        .pool
        .spawn_fn(move || {
          let fingerprint = {
            let mut hasher = Sha256::default();
            hasher.input(&bytes);
            Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
          };

          let put_res = inner.env.begin_rw_txn().and_then(|mut txn| {
            txn.put(db, &fingerprint, &bytes, NO_OVERWRITE).and_then(
            |()| txn.commit(),
          )
          });

          match put_res {
            Ok(()) => Ok(fingerprint),
            Err(KeyExist) => Ok(fingerprint),
            Err(err) => Err(format!(
              "Error storing fingerprint {}: {}",
              fingerprint,
              err.description()
            )),
          }
        })
        .map(move |fingerprint| Digest(fingerprint, len))
        .to_boxed()
    }

    fn load_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
      &self,
      entry_type: EntryType,
      fingerprint: Fingerprint,
      f: F,
    ) -> BoxFuture<Option<T>, String> {
      let db = match entry_type {
        EntryType::Directory => self.inner.directory_store,
        EntryType::File => self.inner.file_store,
      }.clone();

      let store = self.inner.clone();
      self
        .inner
        .pool
        .spawn_fn(move || {
          let ro_txn = store.env.begin_ro_txn().map_err(|err| {
            format!(
              "Failed to begin read transaction: {}",
              err.description().to_string()
            )
          });
          ro_txn.and_then(|txn| match txn.get(db, &fingerprint) {
            Ok(bytes) => Ok(Some(f(bytes))),
            Err(NotFound) => Ok(None),
            Err(err) => Err(format!(
              "Error loading fingerprint {}: {}",
              fingerprint,
              err.description().to_string()
            )),
          })
        })
        .to_boxed()
    }
  }

  #[cfg(test)]
  pub mod tests {
    use futures::Future;
    use super::{ByteStore, EntryType, Fingerprint, ResettablePool};
    use super::super::ByteStore as _ByteStore;
    use lmdb::{DatabaseFlags, Environment, Transaction, WriteFlags};
    use protobuf::Message;
    use std::path::Path;
    use std::sync::Arc;
    use tempdir::TempDir;

    use super::super::tests::{DIRECTORY_HASH, HASH, digest, directory, directory_fingerprint,
                              fingerprint, load_directory_proto_bytes, load_file_bytes, str_bytes};

    #[test]
    fn save_file() {
      let dir = TempDir::new("store").unwrap();

      assert_eq!(
        new_store(dir.path())
          .store_bytes(EntryType::File, str_bytes())
          .wait(),
        Ok(digest())
      );
    }

    #[test]
    fn save_file_is_idempotent() {
      let dir = TempDir::new("store").unwrap();

      new_store(dir.path())
        .store_bytes(EntryType::File, str_bytes())
        .wait()
        .unwrap();
      assert_eq!(
        new_store(dir.path())
          .store_bytes(EntryType::File, str_bytes())
          .wait(),
        Ok(digest())
      );
    }

    #[test]
    fn save_file_collision_preserves_first() {
      let dir = TempDir::new("store").unwrap();

      let fingerprint = Fingerprint::from_hex_string(HASH).unwrap();
      let bogus_value: Vec<u8> = vec![];

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
        load_file_bytes(&new_store(dir.path()), fingerprint),
        Ok(Some(bogus_value.clone()))
      );

      assert_eq!(
        new_store(dir.path())
          .store_bytes(EntryType::File, str_bytes())
          .wait(),
        Ok(digest())
      );

      assert_eq!(
        load_file_bytes(&new_store(dir.path()), fingerprint),
        Ok(Some(bogus_value.clone()))
      );
    }

    #[test]
    fn roundtrip_file() {
      let data = str_bytes();
      let dir = TempDir::new("store").unwrap();

      let store = new_store(dir.path());
      let hash = store
        .store_bytes(EntryType::File, data.clone())
        .wait()
        .unwrap();
      assert_eq!(load_file_bytes(&store, hash.0), Ok(Some(data)));
    }

    #[test]
    fn missing_file() {
      let dir = TempDir::new("store").unwrap();
      assert_eq!(
        load_file_bytes(&new_store(dir.path()), fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn record_and_load_directory_proto() {
      let dir = TempDir::new("store").unwrap();

      assert_eq!(
        &new_store(dir.path())
          .store_bytes(EntryType::Directory, directory().write_to_bytes().unwrap())
          .wait()
          .unwrap()
          .0
          .to_hex(),
        DIRECTORY_HASH
      );

      assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), directory_fingerprint()),
        Ok(Some(directory().write_to_bytes().unwrap()))
      );
    }

    #[test]
    fn missing_directory() {
      let dir = TempDir::new("store").unwrap();

      assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), directory_fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn file_is_not_directory_proto() {
      let dir = TempDir::new("store").unwrap();

      new_store(dir.path())
        .store_bytes(EntryType::File, str_bytes())
        .wait()
        .unwrap();

      assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), fingerprint()),
        Ok(None)
      );
    }

    pub fn new_store<P: AsRef<Path>>(dir: P) -> ByteStore {
      ByteStore::new(dir, Arc::new(ResettablePool::new("test-pool-".to_string()))).unwrap()
    }
  }
}

mod remote {
  use super::{Digest, EntryType};

  use bazel_protos;
  use boxfuture::{Boxable, BoxFuture};
  use futures::{future, Future, Stream};
  use grpcio;
  use std::sync::Arc;

  use hash::Fingerprint;

  #[derive(Clone)]
  pub struct ByteStore {
    address: String,
    env: Arc<grpcio::Environment>,
  }

  impl ByteStore {
    pub fn new(address: String) -> ByteStore {
      // TODO: Pass through a parallelism configuration option here.
      ByteStore {
        address: address,
        env: Arc::new(grpcio::Environment::new(1)),
      }
    }
  }


  impl super::ByteStore for ByteStore {
    fn store_bytes(&self, _entry_type: EntryType, _bytes: Vec<u8>) -> BoxFuture<Digest, String> {
      unimplemented!()
    }

    fn load_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
      &self,
      _entry_type: EntryType,
      fingerprint: Fingerprint,
      f: F,
    ) -> BoxFuture<Option<T>, String> {
      let channel = grpcio::ChannelBuilder::new(self.env.clone()).connect(&self.address);
      let client = bazel_protos::bytestream_grpc::ByteStreamClient::new(channel);
      match client.read(&{
        let mut req = bazel_protos::bytestream::ReadRequest::new();
        // TODO: Pass a size around, or resolve that we don't need to.
        req.set_resource_name(format!("/blobs/{}/{}", fingerprint, -1));
        req.set_read_offset(0);
        // 0 means no limit.
        req.set_read_limit(0);
        req
      }) {
        Ok(stream) =>
        // We shouldn't have to pass around the client here, it's a workaround for
        // https://github.com/pingcap/grpc-rs/issues/123
        future::ok(client)
            .join(stream.map(|r| r.data).concat2())
            .map(|(_client, bytes)| Some(bytes))
            .or_else(|e| match e {
              grpcio::Error::RpcFailure(grpcio::RpcStatus {
                                          status: grpcio::RpcStatusCode::NotFound, ..
                                        }) => Ok(None),
              _ => Err(format!(
                "Error from server in response to CAS read request: {:?}",
                e
              )),
            })
            .map(move |maybe_bytes| {
              maybe_bytes.map(|bytes: Vec<u8>| f(&bytes))
            })
            .to_boxed(),
        Err(err) => future::err(
          format!(
            "Error making CAS read request for {}: {:?}",
            fingerprint,
            err
          )
        ).to_boxed() as BoxFuture<_, _>
      }
    }
  }

  #[cfg(test)]
  mod tests {

    extern crate tempdir;

    use super::ByteStore;
    use super::super::super::test_cas::StubCAS;
    use protobuf::Message;

    use super::super::tests::{directory, directory_fingerprint, fingerprint,
                              load_directory_proto_bytes, load_file_bytes, new_cas, str_bytes};

    #[test]
    fn loads_file() {
      let cas = new_cas(10);

      assert_eq!(
        load_file_bytes(&ByteStore::new(cas.address()), fingerprint()).unwrap(),
        Some(str_bytes())
      );
    }


    #[test]
    fn missing_file() {
      let cas = StubCAS::empty();

      assert_eq!(
        load_file_bytes(&ByteStore::new(cas.address()), fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn load_directory() {
      let cas = new_cas(10);

      assert_eq!(
        load_directory_proto_bytes(&ByteStore::new(cas.address()), directory_fingerprint()),
        Ok(Some(directory().write_to_bytes().unwrap()))
      );
    }

    #[test]
    fn missing_directory() {
      let cas = StubCAS::empty();

      assert_eq!(
        load_directory_proto_bytes(&ByteStore::new(cas.address()), directory_fingerprint()),
        Ok(None)
      );
    }

    #[test]
    fn load_file_grpc_error() {
      let cas = StubCAS::always_errors();

      let error = load_file_bytes(&ByteStore::new(cas.address()), fingerprint())
        .expect_err("Want error");
      assert!(
        error.contains("StubCAS is configured to always fail"),
        format!("Bad error message, got: {}", error)
      )
    }

    #[test]
    fn load_directory_grpc_error() {
      let cas = StubCAS::always_errors();

      let error =
        load_directory_proto_bytes(&ByteStore::new(cas.address()), directory_fingerprint())
          .expect_err("Want error");
      assert!(
        error.contains("StubCAS is configured to always fail"),
        format!("Bad error message, got: {}", error)
      )
    }

    #[test]
    fn fetch_less_than_one_chunk() {
      let cas = new_cas(str_bytes().len() + 1);

      assert_eq!(
        load_file_bytes(&ByteStore::new(cas.address()), fingerprint()),
        Ok(Some(str_bytes()))
      )
    }

    #[test]
    fn fetch_exactly_one_chunk() {
      let cas = new_cas(str_bytes().len());

      assert_eq!(
        load_file_bytes(&ByteStore::new(cas.address()), fingerprint()),
        Ok(Some(str_bytes()))
      )
    }

    #[test]
    fn fetch_multiple_chunks_exact() {
      let cas = new_cas(1);

      assert_eq!(
        load_file_bytes(&ByteStore::new(cas.address()), fingerprint()),
        Ok(Some(str_bytes()))
      )
    }

    #[test]
    fn fetch_multiple_chunks_nonfactor() {
      let cas = new_cas(9);

      assert_eq!(
        load_file_bytes(&ByteStore::new(cas.address()), fingerprint()),
        Ok(Some(str_bytes()))
      )
    }
  }
}

#[cfg(test)]
mod tests {
  use super::{ByteStore, Digest, EntryType, Fingerprint, Store, local};
  use super::super::test_cas::StubCAS;

  use bazel_protos;
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::Future;
  use pool::ResettablePool;
  use protobuf::Message;
  use sha2::Sha256;
  use std::path::Path;
  use std::sync::Arc;
  use tempdir::TempDir;

  pub const STR: &str = "European Burmese";
  pub const HASH: &str = "693d8db7b05e99c6b7a7c0616456039d89c555029026936248085193559a0b5d";
  pub const DIRECTORY_HASH: &str = "63949aa823baf765eff07b946050d76e\
c0033144c785a94d3ebd82baa931cd16";
  const EMPTY_DIRECTORY_HASH: &str = "e3b0c44298fc1c149afbf4c8996fb924\
27ae41e4649b934ca495991b7852b855";

  pub fn fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string(HASH).unwrap()
  }

  pub fn digest() -> Digest {
    Digest(fingerprint(), STR.len())
  }

  pub fn str_bytes() -> Vec<u8> {
    STR.as_bytes().to_owned()
  }

  pub fn directory() -> bazel_protos::remote_execution::Directory {
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
    directory
  }

  pub fn directory_fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string(DIRECTORY_HASH).unwrap()
  }

  pub fn load_file_bytes<B: ByteStore>(
    store: &B,
    fingerprint: Fingerprint,
  ) -> Result<Option<Vec<u8>>, String> {
    store
      .load_bytes_with(EntryType::File, fingerprint, |bytes: &[u8]| bytes.to_vec())
      .wait()
  }

  pub fn load_directory_proto_bytes<B: ByteStore>(
    store: &B,
    fingerprint: Fingerprint,
  ) -> Result<Option<Vec<u8>>, String> {
    store
      .load_bytes_with(
        EntryType::Directory,
        fingerprint,
        |bytes: &[u8]| bytes.to_vec(),
      )
      .wait()
  }

  pub fn new_cas(chunk_size_bytes: usize) -> StubCAS {
    StubCAS::new(
      chunk_size_bytes as i64,
      vec![
        (fingerprint(), str_bytes()),
        (
          directory_fingerprint(),
          directory().write_to_bytes().unwrap()
        ),
      ].into_iter()
        .collect(),
    )
  }

  fn new_store<P: AsRef<Path>>(dir: P, cas_address: String) -> Store {
    Store::backfills_from_remote(
      dir,
      Arc::new(ResettablePool::new("test-pool-".to_string())),
      cas_address,
    ).unwrap()
  }

  #[test]
  fn digest_to_bazel_digest() {
    let digest = Digest(Fingerprint::from_hex_string(HASH).unwrap(), 16);
    let mut bazel_digest = bazel_protos::remote_execution::Digest::new();
    bazel_digest.set_hash(HASH.to_string());
    bazel_digest.set_size_bytes(16);
    assert_eq!(bazel_digest, digest.into());
  }

  #[test]
  fn load_file_prefers_local() {
    let dir = TempDir::new("store").unwrap();

    local::tests::new_store(dir.path())
      .store_bytes(EntryType::File, str_bytes())
      .wait()
      .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_file_bytes_with(fingerprint(), |bytes| Vec::from(bytes))
        .wait(),
      Ok(Some(str_bytes()))
    );
    assert_eq!(0, cas.request_count());
  }

  #[test]
  fn load_directory_prefers_local() {
    let dir = TempDir::new("store").unwrap();

    local::tests::new_store(dir.path())
      .store_bytes(EntryType::Directory, directory().write_to_bytes().unwrap())
      .wait()
      .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_directory(directory_fingerprint())
        .wait(),
      Ok(Some(directory()))
    );
    assert_eq!(0, cas.request_count());
  }

  #[test]
  fn load_file_falls_back_and_backfills() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(1024);
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_file_bytes_with(fingerprint(), |bytes| Vec::from(bytes))
        .wait(),
      Ok(Some(str_bytes())),
      "Read from CAS"
    );
    assert_eq!(1, cas.request_count());
    assert_eq!(
      local::tests::new_store(dir.path())
        .load_bytes_with(
          EntryType::File,
          fingerprint(),
          |bytes: &[u8]| Vec::from(bytes),
        )
        .wait(),
      Ok(Some(str_bytes())),
      "Read from local cache"
    );
  }

  #[test]
  fn load_directory_falls_back_and_backfills() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(1024);
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_directory(directory_fingerprint())
        .wait(),
      Ok(Some(directory()))
    );
    assert_eq!(1, cas.request_count());
    assert_eq!(
      local::tests::new_store(dir.path())
        .load_bytes_with(
          EntryType::Directory,
          directory_fingerprint(),
          |bytes: &[u8]| Vec::from(bytes),
        )
        .wait(),
      Ok(Some(directory().write_to_bytes().unwrap()))
    );
  }

  #[test]
  fn load_file_missing_is_none() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::empty();
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_file_bytes_with(fingerprint(), |bytes| Vec::from(bytes))
        .wait(),
      Ok(None)
    );
    assert_eq!(1, cas.request_count());
  }

  #[test]
  fn load_directory_missing_is_none() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::empty();
    assert_eq!(
      new_store(dir.path(), cas.address())
        .load_directory(directory_fingerprint())
        .wait(),
      Ok(None)
    );
    assert_eq!(1, cas.request_count());
  }


  #[test]
  fn load_file_remote_error_is_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::always_errors();
    let error = new_store(dir.path(), cas.address())
      .load_file_bytes_with(fingerprint(), |bytes| Vec::from(bytes))
      .wait()
      .expect_err("Want error");
    assert_eq!(1, cas.request_count());
    assert!(
      error.contains("StubCAS is configured to always fail"),
      "Bad error message"
    );
  }

  #[test]
  fn load_directory_remote_error_is_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::always_errors();
    let error = new_store(dir.path(), cas.address())
      .load_directory(fingerprint())
      .wait()
      .expect_err("Want error");
    assert_eq!(1, cas.request_count());
    assert!(
      error.contains("StubCAS is configured to always fail"),
      "Bad error message"
    );
  }

  #[test]
  fn malformed_remote_directory_is_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(1024);
    new_store(dir.path(), cas.address())
      .load_directory(fingerprint())
      .wait()
      .expect_err("Want error");

    assert_eq!(
      local::tests::new_store(dir.path())
        .load_bytes_with(EntryType::Directory, fingerprint(), |bytes: &[u8]| {
          Vec::from(bytes)
        })
        .wait(),
      Ok(None)
    );
  }

  #[test]
  fn non_canonical_remote_directory_is_error() {
    let mut directory = directory();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("roland".to_string());
      file.set_digest({
        let mut digest = bazel_protos::remote_execution::Digest::new();
        digest.set_hash(HASH.to_string());
        digest.set_size_bytes(STR.len() as i64);
        digest
      });
      file
    });
    let directory_bytes = directory.write_to_bytes().unwrap();
    let directory_fingerprint = {
      let mut hasher = Sha256::default();
      hasher.input(&directory_bytes);
      Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
    };

    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::new(
      1024,
      vec![(directory_fingerprint.clone(), directory_bytes.clone())]
        .into_iter()
        .collect(),
    );
    new_store(dir.path(), cas.address())
      .load_directory(directory_fingerprint.clone())
      .wait()
      .expect_err("Want error");

    assert_eq!(
      local::tests::new_store(dir.path())
        .load_bytes_with(
          EntryType::Directory,
          directory_fingerprint,
          |bytes: &[u8]| Vec::from(bytes),
        )
        .wait(),
      Ok(None)
    );
  }

  #[test]
  fn wrong_remote_file_bytes_is_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::new(
      1024,
      vec![(fingerprint(), directory().write_to_bytes().unwrap())]
        .into_iter()
        .collect(),
    );
    new_store(dir.path(), cas.address())
      .load_file_bytes_with(fingerprint(), |bytes| Vec::from(bytes))
      .wait()
      .expect_err("Want error");

    assert_eq!(
      local::tests::new_store(dir.path())
        .load_bytes_with(
          EntryType::File,
          fingerprint(),
          |bytes: &[u8]| Vec::from(bytes),
        )
        .wait(),
      Ok(None)
    );
  }

  #[test]
  fn wrong_remote_directory_bytes_is_error() {
    let dir = TempDir::new("store").unwrap();
    let empty_fingerprint = Fingerprint::from_hex_string(EMPTY_DIRECTORY_HASH).unwrap();

    let cas = StubCAS::new(
      1024,
      vec![(empty_fingerprint, directory().write_to_bytes().unwrap())]
        .into_iter()
        .collect(),
    );
    new_store(dir.path(), cas.address())
      .load_file_bytes_with(empty_fingerprint, |bytes| Vec::from(bytes))
      .wait()
      .expect_err("Want error");

    assert_eq!(
      local::tests::new_store(dir.path())
        .load_bytes_with(EntryType::File, empty_fingerprint, |bytes: &[u8]| {
          Vec::from(bytes)
        })
        .wait(),
      Ok(None)
    );
  }
}
