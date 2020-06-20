use async_trait::async_trait;
use parking_lot::Mutex;
use testutil::make_file;

use crate::{
  snapshot_ops::StoreWrapper,
  snapshot_tests::{expand_all_sorted, setup, STR, STR2},
  OneOffStoreFileByDigest, Snapshot, SnapshotOps, Store, SubsetParams,
};
use bazel_protos::remote_execution as remexec;
use fs::{GlobExpansionConjunction, PosixFS, PreparedPathGlobs, StrictGlobMatching};
use hashing::Digest;

use std::collections::HashMap;
use std::fs::create_dir_all;
use std::path::{Path, PathBuf};
use std::sync::Arc;

async fn get_duplicate_rolands<T: StoreWrapper + 'static>(
  store: Store,
  store_wrapper: T,
  base_path: &Path,
  posix_fs: Arc<PosixFS>,
  digester: OneOffStoreFileByDigest,
) -> (Digest, Snapshot, Snapshot) {
  create_dir_all(base_path.join("subdir")).unwrap();

  make_file(&base_path.join("subdir/roland1"), STR.as_bytes(), 0o600);
  let path_stats1 = expand_all_sorted(posix_fs).await;
  let snapshot1 = Snapshot::from_path_stats(store.clone(), digester.clone(), path_stats1)
    .await
    .unwrap();

  let (_store2, tempdir2, posix_fs2, digester2) = setup();
  create_dir_all(tempdir2.path().join("subdir")).unwrap();
  make_file(
    &tempdir2.path().join("subdir/roland2"),
    STR2.as_bytes(),
    0o600,
  );
  let path_stats2 = expand_all_sorted(posix_fs2).await;
  let snapshot2 = Snapshot::from_path_stats(store.clone(), digester2, path_stats2)
    .await
    .unwrap();

  let merged_digest = store_wrapper
    .merge(vec![snapshot1.digest, snapshot2.digest])
    .await
    .unwrap();

  (merged_digest, snapshot1, snapshot2)
}

fn make_subset_params(globs: &[&str]) -> SubsetParams {
  let globs = PreparedPathGlobs::create(
    globs.iter().map(|s| s.to_string()).collect(),
    StrictGlobMatching::Ignore,
    GlobExpansionConjunction::AllMatch,
  )
  .unwrap();
  SubsetParams { globs }
}

#[tokio::test]
async fn subset_single_files() {
  let (store, tempdir, posix_fs, digester) = setup();

  let (merged_digest, snapshot1, snapshot2) = get_duplicate_rolands(
    store.clone(),
    store.clone(),
    tempdir.path(),
    posix_fs.clone(),
    digester,
  )
  .await;

  let subset_params1 = make_subset_params(&["subdir/roland1"]);
  let subset_roland1 = store
    .clone()
    .subset(merged_digest, subset_params1)
    .await
    .unwrap();
  assert_eq!(subset_roland1, snapshot1.digest);

  let subset_params2 = make_subset_params(&["subdir/roland2"]);
  let subset_roland2 = store
    .clone()
    .subset(merged_digest, subset_params2)
    .await
    .unwrap();
  assert_eq!(subset_roland2, snapshot2.digest);
}

#[tokio::test]
async fn subset_recursive_wildcard() {
  let (store, tempdir, posix_fs, digester) = setup();

  let (merged_digest, _, _) = get_duplicate_rolands(
    store.clone(),
    store.clone(),
    tempdir.path(),
    posix_fs.clone(),
    digester,
  )
  .await;

  let subset_params1 = make_subset_params(&["subdir/**"]);
  let subset_roland1 = store
    .clone()
    .subset(merged_digest, subset_params1)
    .await
    .unwrap();
  assert_eq!(merged_digest, subset_roland1);

  // **/* is a commonly-used alias for **.
  let subset_params2 = make_subset_params(&["subdir/**/*"]);
  let subset_roland2 = store
    .clone()
    .subset(merged_digest, subset_params2)
    .await
    .unwrap();
  assert_eq!(merged_digest, subset_roland2);
}

#[derive(Clone)]
struct LoadTrackingStore {
  store: Store,
  load_counts: Arc<Mutex<HashMap<Digest, usize>>>,
}

#[async_trait]
impl StoreWrapper for LoadTrackingStore {
  async fn load_file_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
    &self,
    digest: Digest,
    f: F,
  ) -> Result<Option<T>, String> {
    Ok(
      Store::load_file_bytes_with(&self.store, digest, f)
        .await?
        .map(|(value, _)| value),
    )
  }

  async fn load_directory(&self, digest: Digest) -> Result<Option<remexec::Directory>, String> {
    {
      let mut counts = self.load_counts.lock();
      let entry = counts.entry(digest).or_insert(0);
      *entry += 1;
    }
    Ok(
      Store::load_directory(&self.store, digest)
        .await?
        .map(|(dir, _)| dir),
    )
  }

  async fn load_directory_or_err(&self, digest: Digest) -> Result<remexec::Directory, String> {
    {
      let mut counts = self.load_counts.lock();
      let entry = counts.entry(digest).or_insert(0);
      *entry += 1;
    }
    Snapshot::get_directory_or_err(self.store.clone(), digest).await
  }

  async fn record_directory(&self, directory: &remexec::Directory) -> Result<Digest, String> {
    Store::record_directory(&self.store, directory, true).await
  }
}

#[tokio::test]
async fn subset_tracking_load_counts() {
  let (store, tempdir, posix_fs, digester) = setup();

  let load_tracking_store = LoadTrackingStore {
    store: store.clone(),
    load_counts: Arc::new(Mutex::new(HashMap::new())),
  };

  let (merged_digest, _, _) = get_duplicate_rolands(
    store.clone(),
    load_tracking_store.clone(),
    tempdir.path(),
    posix_fs.clone(),
    digester,
  )
  .await;

  let subdir_digest = load_tracking_store
    .strip_prefix(merged_digest, PathBuf::from("subdir"))
    .await
    .unwrap();

  let num_subdir_loads = {
    let num_loads: HashMap<Digest, usize> = load_tracking_store.load_counts.lock().clone();
    *num_loads.get(&subdir_digest).unwrap()
  };
  assert_eq!(1, num_subdir_loads);

  let subset_everything = make_subset_params(&["**/*"]);
  let subset_result = load_tracking_store
    .subset(merged_digest, subset_everything)
    .await
    .unwrap();
  assert_eq!(merged_digest, subset_result);
  // Verify that no extra digest loads for the subdirectory "subdir" are performed when a ** glob is
  // used, which should just take the digest unmodified, and not attempt to examine its contents.
  let num_loads: HashMap<Digest, usize> = load_tracking_store.load_counts.lock().clone();
  assert_eq!(num_subdir_loads, *num_loads.get(&subdir_digest).unwrap());

  // Check that the same result occurs when the trailing glob is just /**.
  let subset_everything = make_subset_params(&["**"]);
  let subset_result = load_tracking_store
    .subset(merged_digest, subset_everything)
    .await
    .unwrap();
  assert_eq!(merged_digest, subset_result);
  let num_loads: HashMap<Digest, usize> = load_tracking_store.load_counts.lock().clone();
  assert_eq!(num_subdir_loads, *num_loads.get(&subdir_digest).unwrap());
}
