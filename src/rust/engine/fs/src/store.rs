use bazel_protos;
use boxfuture::{Boxable, BoxFuture};
use digest::{Digest as DigestTrait, FixedOutput};
use futures::{future, Future, Stream};
use futures_cpupool::CpuFuture;
use grpcio;
use lmdb::{Database, DatabaseFlags, Environment, NO_OVERWRITE, Transaction};
use lmdb::Error::{KeyExist, NotFound};
use protobuf::core::Message;
use sha2::Sha256;
use std::error::Error;
use std::path::Path;
use std::sync::{Arc, Mutex};

use hash::Fingerprint;
use pool::ResettablePool;

///
/// A content-addressed store of file contents, and Directories.
///
/// Store keeps content on disk, and can optionally delegate to backfill its on-disk storage by
/// fetching files from a remote server which implements the gRPC bytestream interface
/// (see https://github.com/googleapis/googleapis/blob/master/google/bytestream/bytestream.proto)
/// as specified by the gRPC remote execution interface (see
/// https://github.com/googleapis/googleapis/blob/master/google/devtools/remoteexecution/v1test/)
///
/// When fetching contents remotely, verifies that the fetched content has the correct digest, and
/// that any Directory protos are valid and canonical.
///
/// In the future, it will gain the ability to write back to the gRPC server, too.
///
#[derive(Clone)]
pub struct Store {
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
  // If a grpc env is present, reads will be transparently backfilled using it.
  grpc_env: Option<GrpcEnvironment>,
}

#[derive(Clone)]
struct GrpcEnvironment {
  address: String,
  env: Arc<grpcio::Environment>,
}

impl Store {
  pub fn new<P: AsRef<Path>>(
    path: P,
    pool: Arc<ResettablePool>,
    cas_address: Option<String>,
  ) -> Result<Store, String> {
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
        pool: pool,
        file_store: file_database,
        directory_store: directory_database,
        // TODO: Pass through a parallelism configuration option here.
        grpc_env: cas_address.map(|address| {
          GrpcEnvironment {
            address: address,
            env: Arc::new(grpcio::Environment::new(1)),
          }
        }),
      }),
    })
  }

  pub fn store_file_bytes(&self, bytes: Vec<u8>) -> BoxFuture<Digest, String> {
    let len = bytes.len();
    self
      .store_bytes(bytes, self.inner.file_store.clone())
      .map(move |fingerprint| Digest(fingerprint, len))
      .to_boxed()
  }

  fn store_bytes(&self, bytes: Vec<u8>, db: Database) -> CpuFuture<Fingerprint, String> {
    let store = self.clone();
    self.inner.pool.spawn_fn(move || {
      let fingerprint = {
        let mut hasher = Sha256::default();
        hasher.input(&bytes);
        Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
      };

      let put_res = store.inner.env.begin_rw_txn().and_then(|mut txn| {
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
  }

  pub fn load_file_bytes(&self, fingerprint: Fingerprint) -> BoxFuture<Option<Vec<u8>>, String> {
    self.load_bytes(fingerprint, self.inner.file_store.clone())
  }

  pub fn load_file_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + 'static>(
    &self,
    fingerprint: Fingerprint,
    f: F,
  ) -> BoxFuture<Option<T>, String> {
    self.load_bytes_with(fingerprint, self.inner.file_store.clone(), f)
  }

  pub fn load_directory_proto_bytes(
    &self,
    fingerprint: Fingerprint,
  ) -> BoxFuture<Option<Vec<u8>>, String> {
    self.load_bytes(fingerprint, self.inner.directory_store.clone())
  }

  pub fn load_directory_proto(
    &self,
    fingerprint: Fingerprint,
  ) -> BoxFuture<Option<bazel_protos::remote_execution::Directory>, String> {
    self
      .load_directory_proto_bytes(fingerprint)
      .and_then(move |res| match res {
        Some(bytes) => {
          let mut proto = bazel_protos::remote_execution::Directory::new();
          proto
            .merge_from_bytes(&bytes)
            .map_err(|e| {
              format!("Error deserializing proto {}: {}", fingerprint, e)
            })
            .and(Ok(Some(proto)))
        }
        None => Ok(None),
      })
      .to_boxed()
  }

  fn load_bytes(
    &self,
    fingerprint: Fingerprint,
    db: Database,
  ) -> BoxFuture<Option<Vec<u8>>, String> {
    self.load_bytes_with(fingerprint, db, |bytes| Vec::from(bytes))
  }

  fn load_bytes_with<T: Send + 'static + Sized, F: Fn(&[u8]) -> T + Send + 'static>(
    &self,
    fingerprint: Fingerprint,
    db: Database,
    f: F,
  ) -> BoxFuture<Option<T>, String> {
    let grpc_env = self.inner.grpc_env.clone();
    let store = self.clone();

    let f = Arc::new(Mutex::new(f));
    self
      .load_bytes_local_with(fingerprint, db, f.clone())
      .map(move |maybe_bytes| match maybe_bytes {
        Some(value) => future::ok(Some(value)).to_boxed() as BoxFuture<_, _>,
        None => {
          match grpc_env {
            Some(GrpcEnvironment { address, env }) => {
              store.load_bytes_remote_with(fingerprint, db, f, &address, env)
            }
            None => future::ok(None).to_boxed() as BoxFuture<_, _>,
          }
        }
      })
      .to_boxed()
      .flatten()
      .to_boxed()
  }

  fn load_bytes_local_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + 'static>(
    &self,
    fingerprint: Fingerprint,
    db: Database,
    f: Arc<Mutex<F>>,
  ) -> CpuFuture<Option<T>, String> {
    let store = self.inner.clone();
    self.inner.pool.spawn_fn(move || {
      let ro_txn = store.env.begin_ro_txn().map_err(|err| {
        format!(
          "Failed to begin read transaction: {}",
          err.description().to_string()
        )
      });
      ro_txn.and_then(|txn| match txn.get(db, &fingerprint) {
        Ok(bytes) => {
          let f = f.lock().unwrap();
          Ok(Some(f(bytes)))
        }
        Err(NotFound) => Ok(None),
        Err(err) => Err(format!(
          "Error loading fingerprint {}: {}",
          fingerprint,
          err.description().to_string()
        )),
      })
    })
  }

  fn load_bytes_remote_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + 'static>(
    &self,
    fingerprint: Fingerprint,
    db: Database,
    f: Arc<Mutex<F>>,
    cas_address: &str,
    env: Arc<grpcio::Environment>,
  ) -> BoxFuture<Option<T>, String> {
    let channel = grpcio::ChannelBuilder::new(env).connect(cas_address);
    let client = bazel_protos::bytestream_grpc::ByteStreamClient::new(channel);
    let stream = client.read(&{
      let mut req = bazel_protos::bytestream::ReadRequest::new();
      // TODO: Pass a size around, or resolve that we don't need to.
      req.set_resource_name(format!("/blobs/{}/{}", fingerprint, -1));
      req.set_read_offset(0);
      // 0 means no limit.
      req.set_read_limit(0);
      req
    });

    let store_copy = self.clone();
    let directory_db = self.inner.directory_store;

    // We shouldn't have to pass around the client here, it's a workaround for
    // https://github.com/pingcap/grpc-rs/issues/123
    future::ok(client).join(stream.map(|r| r.data).concat2())
      .map(|(_client, bytes)| Some(bytes))
      .or_else(|e| match e {
        grpcio::Error::RpcFailure(grpcio::RpcStatus {
                                    status: grpcio::RpcStatusCode::NotFound, ..
                                  }) => Ok(None),
        _ => Err(format!("Error making CAS read request: {:?}", e)),
      })
      .and_then(move |maybe_bytes: Option<Vec<u8>>| match maybe_bytes {
        Some(bytes) => {
          if db == directory_db {
            match Store::validate_directory(&bytes) {
              Err(e) => {
                return future::err(format!("Directory proto was not canonical: {}", e))
                  .to_boxed() as BoxFuture<_, _>
              }
              _ => {}
            }
          }
          store_copy
                  .store_bytes(bytes.clone(), db)
                  .and_then(move |retrieved_fingerprint| {
                    if retrieved_fingerprint == fingerprint {
                      Ok(())
                    } else {
                      Err(
                        format!(
                          "Fetched content from remote CAS but it had the wrong fingerprint \
(wanted {} got {})",
                          fingerprint,
                          retrieved_fingerprint))
                    }
                  }).map(move |()| {
                let f = f.lock().unwrap();
                Some(f(&bytes))
              }).to_boxed()
        }
        None => future::ok(None).to_boxed() as BoxFuture<_, _>,
      })
      .to_boxed()
  }

  fn validate_directory(bytes: &[u8]) -> Result<(), String> {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    // We rely on the Rust proto implementation erroring if an invalid proto is specified, e.g. if
    // there are duplicate copies of the same non-repeated field.
    directory.merge_from_bytes(&bytes).map_err(|e| {
      format!("Error deserializing Directory proto: {:?}", e)
    })?;
    bazel_protos::verify_directory_canonical(&directory)
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
  ) -> BoxFuture<Digest, String> {
    let store = self.clone();
    future::result(directory.write_to_bytes().map_err(|e| {
      format!(
        "Error serializing directory proto {:?}: {}",
        directory,
        e.description()
      )
    })).and_then(move |bytes| {
      let len = bytes.len();

      store
        .store_bytes(bytes, store.inner.directory_store.clone())
        .map(move |fingerprint| Digest(fingerprint, len))
    })
      .to_boxed()
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
  use digest::{Digest as DigestTrait, FixedOutput};
  use futures::Future;
  use super::{Digest, Fingerprint, ResettablePool, Store};
  use super::super::test_cas::StubCAS;
  use lmdb::{DatabaseFlags, Environment, Transaction, WriteFlags};
  use protobuf::Message;
  use sha2::Sha256;
  use std::path::Path;
  use std::sync::Arc;
  use tempdir::TempDir;


  const STR: &str = "European Burmese";
  const HASH: &str = "693d8db7b05e99c6b7a7c0616456039d89c555029026936248085193559a0b5d";
  const DIRECTORY_HASH: &str = "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16";

  fn fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string(HASH).unwrap()
  }

  fn digest() -> Digest {
    Digest(fingerprint(), STR.len())
  }

  fn str_bytes() -> Vec<u8> {
    STR.as_bytes().to_owned()
  }

  fn directory() -> bazel_protos::remote_execution::Directory {
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

  fn directory_fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string(DIRECTORY_HASH).unwrap()
  }

  #[test]
  fn save_file() {
    let dir = TempDir::new("store").unwrap();

    assert_eq!(
      new_store(dir.path(), None)
        .store_file_bytes(str_bytes())
        .wait(),
      Ok(digest())
    );
  }

  #[test]
  fn save_file_is_idempotent() {
    let dir = TempDir::new("store").unwrap();

    new_store(dir.path(), None)
      .store_file_bytes(str_bytes())
      .wait()
      .unwrap();
    assert_eq!(
      new_store(dir.path(), None)
        .store_file_bytes(str_bytes())
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
      new_store(dir.path(), None)
        .load_file_bytes(fingerprint)
        .wait(),
      Ok(Some(bogus_value.clone()))
    );

    assert_eq!(
      new_store(dir.path(), None)
        .store_file_bytes(str_bytes())
        .wait(),
      Ok(digest())
    );

    assert_eq!(
      new_store(dir.path(), None)
        .load_file_bytes(fingerprint)
        .wait(),
      Ok(Some(bogus_value))
    );
  }

  #[test]
  fn roundtrip_file() {
    let data = str_bytes();
    let dir = TempDir::new("store").unwrap();

    let store = new_store(dir.path(), None);
    let hash = store.store_file_bytes(data.clone()).wait().unwrap();
    assert_eq!(store.load_file_bytes(hash.0).wait(), Ok(Some(data)));
  }

  #[test]
  fn loads_file_from_cas() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(10);

    let bytes = new_store(dir.path(), Some(cas.address()))
      .load_file_bytes(fingerprint())
      .wait()
      .unwrap();
    assert_eq!(bytes, Some(str_bytes()));
  }

  #[test]
  fn wrong_file_from_cas_is_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::new(
      1024,
      vec![(directory_fingerprint(), str_bytes())]
        .into_iter()
        .collect(),
    );
    let store = new_store(dir.path(), Some(cas.address()));
    let error = store
      .load_file_bytes(directory_fingerprint())
      .wait()
      .expect_err("Want error");
    assert!(
      error.contains("fingerprint"),
      format!("Bad error message, got: {}", error)
    );
    assert!(
      error.contains(&fingerprint().to_hex()),
      format!("Bad error message, got: {}", error)
    );
    assert!(
      error.contains(&directory_fingerprint().to_hex()),
      format!("Bad error message, got: {}", error)
    );

    // Make sure we didn't store bad data for future look-up.
    let error = store
      .load_file_bytes(directory_fingerprint())
      .wait()
      .expect_err("Want error");
    assert!(
      error.contains("fingerprint"),
      format!("Bad error message, got: {}", error)
    );
  }

  #[test]
  fn missing_file_local_only() {
    let dir = TempDir::new("store").unwrap();
    assert_eq!(
      new_store(dir.path(), None)
        .load_file_bytes(Fingerprint::from_hex_string(HASH).unwrap())
        .wait(),
      Ok(None)
    );
  }

  #[test]
  fn missing_file_local_and_remote() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::empty();

    assert_eq!(
      new_store(dir.path(), Some(cas.address()))
        .load_file_bytes(Fingerprint::from_hex_string(HASH).unwrap())
        .wait(),
      Ok(None)
    );
  }

  #[test]
  fn record_and_load_directory_proto() {
    let dir = TempDir::new("store").unwrap();

    assert_eq!(
      &new_store(dir.path(), None)
        .record_directory(&directory())
        .wait()
        .unwrap()
        .0
        .to_hex(),
      DIRECTORY_HASH
    );

    assert_eq!(
      new_store(dir.path(), None)
        .load_directory_proto(directory_fingerprint())
        .wait(),
      Ok(Some(directory()))
    );

    assert_eq!(
      new_store(dir.path(), None)
        .load_directory_proto_bytes(directory_fingerprint())
        .wait(),
      Ok(Some(directory().write_to_bytes().unwrap()))
    );
  }

  #[test]
  fn load_directory_remote() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::new(
      10,
      vec![
        (
          directory_fingerprint(),
          directory().write_to_bytes().unwrap()
        ),
      ].into_iter()
        .collect(),
    );

    assert_eq!(
      new_store(dir.path(), Some(cas.address()))
        .load_directory_proto(directory_fingerprint())
        .wait(),
      Ok(Some(directory()))
    );
  }

  #[test]
  fn load_badly_sorted_directory_remote() {
    let badly_sorted_directory = {
      let mut directory = bazel_protos::remote_execution::Directory::new();

      let digest = {
        let mut digest = bazel_protos::remote_execution::Digest::new();
        digest.set_hash(HASH.to_string());
        digest.set_size_bytes(STR.len() as i64);
        digest
      };

      directory.mut_files().push({
        let mut file = bazel_protos::remote_execution::FileNode::new();
        file.set_name("simba".to_string());
        file.set_digest(digest.clone());
        file.set_is_executable(false);
        file
      });

      directory.mut_files().push({
        let mut file = bazel_protos::remote_execution::FileNode::new();
        file.set_name("roland".to_string());
        file.set_digest(digest);
        file.set_is_executable(false);
        file
      });
      directory
    };

    let directory_bytes = badly_sorted_directory.write_to_bytes().unwrap();

    let directory_fingerprint = {
      let mut hasher = Sha256::default();
      hasher.input(&directory_bytes);
      Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
    };

    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::new(
      1024,
      vec![(directory_fingerprint, directory_bytes)]
        .into_iter()
        .collect(),
    );

    let error = new_store(dir.path(), Some(cas.address()))
      .load_directory_proto(directory_fingerprint)
      .wait()
      .expect_err("Want error");
    assert!(
      error.contains("canonical"),
      format!("Bad error message, got: {}", error)
    )
  }

  #[test]
  fn load_malformed_directory_remote() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(16);

    let error = new_store(dir.path(), Some(cas.address()))
      .load_directory_proto(fingerprint())
      .wait()
      .expect_err("Want error");
    assert!(
      error.contains("Error deserializing Directory proto"),
      format!("Bad error message, got: {}", error)
    )
  }

  #[test]
  fn missing_directory_local_only() {
    let dir = TempDir::new("store").unwrap();

    assert_eq!(
      new_store(dir.path(), None)
        .load_directory_proto(directory_fingerprint())
        .wait(),
      Ok(None)
    );
  }

  #[test]
  fn missing_directory_local_and_remote() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::empty();

    assert_eq!(
      new_store(dir.path(), Some(cas.address()))
        .load_directory_proto(directory_fingerprint())
        .wait(),
      Ok(None)
    );
  }

  #[test]
  fn load_file_grpc_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::always_errors();

    let error = new_store(dir.path(), Some(cas.address()))
      .load_file_bytes(fingerprint())
      .wait()
      .expect_err("Want error");
    assert!(
      error.contains("StubCAS is configured to always fail"),
      format!("Bad error message, got: {}", error)
    )
  }

  #[test]
  fn load_directory_grpc_error() {
    let dir = TempDir::new("store").unwrap();

    let cas = StubCAS::always_errors();

    let error = new_store(dir.path(), Some(cas.address()))
      .load_directory_proto(directory_fingerprint())
      .wait()
      .expect_err("Want error");
    assert!(
      error.contains("StubCAS is configured to always fail"),
      format!("Bad error message, got: {}", error)
    )
  }

  #[test]
  fn fetch_less_than_one_chunk() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(STR.len() + 1);

    assert_eq!(
      new_store(dir.path(), Some(cas.address()))
        .load_file_bytes(fingerprint())
        .wait(),
      Ok(Some(str_bytes()))
    )
  }

  #[test]
  fn fetch_exactly_one_chunk() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(STR.len());

    assert_eq!(
      new_store(dir.path(), Some(cas.address()))
        .load_file_bytes(fingerprint())
        .wait(),
      Ok(Some(str_bytes()))
    )
  }

  #[test]
  fn fetch_multiple_chunks_exact() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(1);

    assert_eq!(
      new_store(dir.path(), Some(cas.address()))
        .load_file_bytes(fingerprint())
        .wait(),
      Ok(Some(str_bytes()))
    )
  }

  #[test]
  fn fetch_multiple_chunks_nonfactor() {
    let dir = TempDir::new("store").unwrap();

    let cas = new_cas(9);

    assert_eq!(
      new_store(dir.path(), Some(cas.address()))
        .load_file_bytes(fingerprint())
        .wait(),
      Ok(Some(str_bytes()))
    )
  }

  #[test]
  fn file_is_not_directory_proto() {
    let dir = TempDir::new("store").unwrap();

    new_store(dir.path(), None)
      .store_file_bytes(str_bytes())
      .wait()
      .unwrap();

    assert_eq!(
      new_store(dir.path(), None)
        .load_directory_proto(Fingerprint::from_hex_string(HASH).unwrap())
        .wait(),
      Ok(None)
    );

    assert_eq!(
      new_store(dir.path(), None)
        .load_directory_proto_bytes(Fingerprint::from_hex_string(HASH).unwrap())
        .wait(),
      Ok(None)
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

  fn new_store<P: AsRef<Path>>(dir: P, cas_address: Option<String>) -> Store {
    Store::new(
      dir,
      Arc::new(ResettablePool::new("test-pool-".to_string())),
      cas_address,
    ).unwrap()
  }

  fn new_cas(chunk_size_bytes: usize) -> StubCAS {
    StubCAS::new(
      chunk_size_bytes as i64,
      vec![(fingerprint(), str_bytes())].into_iter().collect(),
    )
  }
}
