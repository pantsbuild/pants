use crate::cargo_fetcher::*;

use fs;
use sharded_lmdb::ShardedLmdb;
use store::Store;
use task_executor::Executor;

use cargo_fetcher;
use tempfile::TempDir;
use tokio::runtime::Handle;

use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

fn new_executor() -> Executor {
  Executor::new(Handle::current())
}

fn new_store<P: AsRef<Path>>(dir: P, executor: Executor) -> Store {
  Store::local_only(executor, &dir).unwrap()
}

struct Environment {
  executor: Executor,
  #[allow(dead_code)]
  temp_dir: TempDir,
}

// 50 MB - I didn't pick that number but it seems reasonable.
const MAX_LMDB_SIZE: usize = 50 * 1024 * 1024;

impl Environment {
  pub fn new() -> io::Result<Self> {
    Ok(Environment {
      executor: new_executor(),
      temp_dir: TempDir::new()?,
    })
  }

  fn root_dir(&self) -> PathBuf {
    self.temp_dir.path().to_path_buf()
  }

  fn download_dir(&self) -> PathBuf {
    let ret = self.root_dir().join("downloads");
    fs::safe_create_dir_all(&ret).unwrap();
    ret
  }

  pub fn index_download_dir(&self) -> PathBuf {
    self.download_dir().join(registry_index_reldir())
  }

  fn store(&self) -> Store {
    new_store(&self.root_dir(), self.executor.clone())
  }

  fn new_lmdb<P: AsRef<Path>>(&self, relative_dir: P) -> ShardedLmdb {
    let dir = self.root_dir().join(relative_dir.as_ref());
    fs::safe_create_dir_all(&dir).unwrap();
    ShardedLmdb::new(dir, MAX_LMDB_SIZE, self.executor.clone()).unwrap()
  }

  fn krate_lookup(&self) -> ShardedLmdb {
    self.new_lmdb("krate_lookup")
  }

  fn krate_data(&self) -> ShardedLmdb {
    self.new_lmdb("krate_data")
  }

  fn krate_digest_mapping(&self) -> ShardedLmdb {
    self.new_lmdb("krate_digest_mapping")
  }

  fn fetch_cache(&self) -> ShardedLmdb {
    self.new_lmdb("fetch_cache")
  }

  pub fn make_fetcher(&self) -> CargoPackageFetcher {
    CargoPackageFetcher {
      krate_lookup: self.krate_lookup(),
      krate_data: self.krate_data(),
      krate_digest_mapping: self.krate_digest_mapping(),
      fetch_cache: self.fetch_cache(),
      store: self.store(),
      executor: self.executor.clone(),
      download_dir: self.download_dir(),
      timeout: Duration::from_secs(10),
    }
  }
}

#[tokio::test]
async fn fetch_package() {
  let environment = Environment::new().unwrap();
  let fetcher = environment.make_fetcher();

  // This is a known-good sha for this version of the bytes crate.
  let bytes_krate = Krate {
    name: "bytes".to_string(),
    version: "0.5.4".to_string(),
    source: cargo_fetcher::Source::CratesIo(
      "130aac562c0dd69c56b3b1cc8ffd2e17be31d0b6c25b61c96b76231aa23e39e1".to_string(),
    ),
  };

  let result = fetcher
    .fetch_packages(&[bytes_krate.clone()])
    .await
    .unwrap();

  // Check that the recorded registry revision was the same as in the actual checked-out git dir for
  // the registry.
  let index_download_dir = environment.index_download_dir();
  assert_eq!(
    result.registry_index_revision(),
    get_registry_git_revision(index_download_dir, fetcher.executor.clone())
      .await
      .unwrap(),
  );

  // Check that the registry digest was uploaded to the store.
  let registry_digest = fetcher
    .lookup_digest(&result.current_registry_index_krate)
    .await
    .unwrap()
    .unwrap();
  assert!(fetcher
    .store
    .load_directory(registry_digest)
    .await
    .unwrap()
    .is_some());

  // Check that the `bytes` crate was uploaded to the store.
  let bytes_digest = fetcher.lookup_digest(&bytes_krate).await.unwrap().unwrap();
  assert!(fetcher
    .store
    .load_directory(bytes_digest)
    .await
    .unwrap()
    .is_some());

  // Check that the cache for the fetch was populated, so we won't have to make any network calls at
  // all if we've run this resolve before.
  assert!(fetcher
    .try_cached_fetch(&[bytes_krate.clone()])
    .await
    .unwrap()
    .is_some());
}
