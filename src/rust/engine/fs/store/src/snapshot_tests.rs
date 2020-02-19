use futures01::future::Future;
use hashing::{Digest, Fingerprint};
use tempfile;
use testutil::data::TestDirectory;
use testutil::make_file;

use crate::{OneOffStoreFileByDigest, Snapshot, Store};
use fs::{
  Dir, File, GlobExpansionConjunction, GlobMatching, PathGlobs, PathStat, PosixFS,
  StrictGlobMatching,
};

use std;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use workunit_store::WorkUnitStore;

const STR: &str = "European Burmese";

fn setup() -> (
  Store,
  tempfile::TempDir,
  Arc<PosixFS>,
  OneOffStoreFileByDigest,
  task_executor::Executor,
) {
  let executor = task_executor::Executor::new();
  // TODO: Pass a remote CAS address through.
  let store = Store::local_only(
    executor.clone(),
    tempfile::Builder::new()
      .prefix("lmdb_store")
      .tempdir()
      .unwrap(),
  )
  .unwrap();
  let dir = tempfile::Builder::new().prefix("root").tempdir().unwrap();
  let posix_fs = Arc::new(PosixFS::new(dir.path(), &[], task_executor::Executor::new()).unwrap());
  let file_saver = OneOffStoreFileByDigest::new(store.clone(), posix_fs.clone());
  (store, dir, posix_fs, file_saver, executor)
}

#[test]
fn snapshot_one_file() {
  let (store, dir, posix_fs, digester, runtime) = setup();

  let file_name = PathBuf::from("roland");
  make_file(&dir.path().join(&file_name), STR.as_bytes(), 0o600);

  let path_stats = expand_all_sorted(posix_fs, &runtime);
  let snapshot = runtime
    .block_on(Snapshot::from_path_stats(
      store,
      &digester,
      path_stats.clone(),
      WorkUnitStore::new(),
    ))
    .unwrap();
  assert_eq!(
    snapshot,
    Snapshot {
      digest: Digest(
        Fingerprint::from_hex_string(
          "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16",
        )
        .unwrap(),
        80,
      ),
      path_stats: path_stats,
    }
  );
}

#[test]
fn snapshot_recursive_directories() {
  let (store, dir, posix_fs, digester, runtime) = setup();

  let cats = PathBuf::from("cats");
  let roland = cats.join("roland");
  std::fs::create_dir_all(&dir.path().join(cats)).unwrap();
  make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

  let path_stats = expand_all_sorted(posix_fs, &runtime);
  let snapshot = runtime
    .block_on(Snapshot::from_path_stats(
      store,
      &digester,
      path_stats.clone(),
      WorkUnitStore::new(),
    ))
    .unwrap();
  assert_eq!(
    snapshot,
    Snapshot {
      digest: Digest(
        Fingerprint::from_hex_string(
          "8b1a7ea04eaa2527b35683edac088bc826117b53b7ec6601740b55e20bce3deb",
        )
        .unwrap(),
        78,
      ),
      path_stats: path_stats,
    }
  );
}

#[test]
fn snapshot_from_digest() {
  let (store, dir, posix_fs, digester, runtime) = setup();

  let cats = PathBuf::from("cats");
  let roland = cats.join("roland");
  std::fs::create_dir_all(&dir.path().join(cats)).unwrap();
  make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

  let path_stats = expand_all_sorted(posix_fs, &runtime);
  let expected_snapshot = runtime
    .block_on(Snapshot::from_path_stats(
      store.clone(),
      &digester,
      path_stats.clone(),
      WorkUnitStore::new(),
    ))
    .unwrap();
  assert_eq!(
    expected_snapshot,
    runtime
      .block_on(Snapshot::from_digest(
        store,
        expected_snapshot.digest,
        WorkUnitStore::new()
      ))
      .unwrap()
  );
}

#[test]
fn snapshot_recursive_directories_including_empty() {
  let (store, dir, posix_fs, digester, runtime) = setup();

  let cats = PathBuf::from("cats");
  let roland = cats.join("roland");
  let dogs = PathBuf::from("dogs");
  let llamas = PathBuf::from("llamas");
  std::fs::create_dir_all(&dir.path().join(&cats)).unwrap();
  std::fs::create_dir_all(&dir.path().join(&dogs)).unwrap();
  std::fs::create_dir_all(&dir.path().join(&llamas)).unwrap();
  make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

  let sorted_path_stats = expand_all_sorted(posix_fs, &runtime);
  let mut unsorted_path_stats = sorted_path_stats.clone();
  unsorted_path_stats.reverse();
  assert_eq!(
    runtime
      .block_on(Snapshot::from_path_stats(
        store,
        &digester,
        unsorted_path_stats.clone(),
        WorkUnitStore::new(),
      ))
      .unwrap(),
    Snapshot {
      digest: Digest(
        Fingerprint::from_hex_string(
          "fbff703bdaac62accf2ea5083bcfed89292073bf710ef9ad14d9298c637e777b",
        )
        .unwrap(),
        232,
      ),
      path_stats: sorted_path_stats,
    }
  );
}

#[test]
fn merge_directories_two_files() {
  let (store, _, _, _, runtime) = setup();

  let containing_roland = TestDirectory::containing_roland();
  let containing_treats = TestDirectory::containing_treats();

  runtime
    .block_on(store.record_directory(&containing_roland.directory(), false))
    .expect("Storing roland directory");
  runtime
    .block_on(store.record_directory(&containing_treats.directory(), false))
    .expect("Storing treats directory");

  let result = runtime.block_on(Snapshot::merge_directories(
    store,
    vec![containing_treats.digest(), containing_roland.digest()],
    WorkUnitStore::new(),
  ));

  assert_eq!(
    result,
    Ok(TestDirectory::containing_roland_and_treats().digest())
  );
}

#[test]
fn merge_directories_clashing_files() {
  let (store, _, _, _, runtime) = setup();

  let containing_roland = TestDirectory::containing_roland();
  let containing_wrong_roland = TestDirectory::containing_wrong_roland();

  runtime
    .block_on(store.record_directory(&containing_roland.directory(), false))
    .expect("Storing roland directory");
  runtime
    .block_on(store.record_directory(&containing_wrong_roland.directory(), false))
    .expect("Storing wrong roland directory");

  let err = runtime
    .block_on(Snapshot::merge_directories(
      store,
      vec![containing_roland.digest(), containing_wrong_roland.digest()],
      WorkUnitStore::new(),
    ))
    .expect_err("Want error merging");

  assert!(
    err.contains("roland"),
    "Want error message to contain roland but was: {}",
    err
  );
}

#[test]
fn merge_directories_same_files() {
  let (store, _, _, _, runtime) = setup();

  let containing_roland = TestDirectory::containing_roland();
  let containing_roland_and_treats = TestDirectory::containing_roland_and_treats();

  runtime
    .block_on(store.record_directory(&containing_roland.directory(), false))
    .expect("Storing roland directory");
  runtime
    .block_on(store.record_directory(&containing_roland_and_treats.directory(), false))
    .expect("Storing treats directory");

  let result = runtime.block_on(Snapshot::merge_directories(
    store,
    vec![
      containing_roland.digest(),
      containing_roland_and_treats.digest(),
    ],
    WorkUnitStore::new(),
  ));

  assert_eq!(
    result,
    Ok(TestDirectory::containing_roland_and_treats().digest())
  );
}

#[test]
fn snapshot_merge_two_files() {
  let (store, tempdir, _, digester, runtime) = setup();

  let common_dir_name = "tower";
  let common_dir = PathBuf::from(common_dir_name);

  let dir = make_dir_stat(tempdir.path(), &common_dir);
  let file1 = make_file_stat(
    tempdir.path(),
    &common_dir.join("roland"),
    STR.as_bytes(),
    false,
  );
  let file2 = make_file_stat(
    tempdir.path(),
    &common_dir.join("susannah"),
    STR.as_bytes(),
    true,
  );

  let snapshot1 = runtime
    .block_on(Snapshot::from_path_stats(
      store.clone(),
      &digester,
      vec![dir.clone(), file1.clone()],
      WorkUnitStore::new(),
    ))
    .unwrap();

  let snapshot2 = runtime
    .block_on(Snapshot::from_path_stats(
      store.clone(),
      &digester,
      vec![dir.clone(), file2.clone()],
      WorkUnitStore::new(),
    ))
    .unwrap();

  let merged = runtime
    .block_on(Snapshot::merge(
      store.clone(),
      &[snapshot1, snapshot2],
      WorkUnitStore::new(),
    ))
    .unwrap();
  let merged_root_directory = runtime
    .block_on(store.load_directory(merged.digest, WorkUnitStore::new()))
    .unwrap()
    .unwrap()
    .0;

  assert_eq!(merged.path_stats, vec![dir, file1, file2]);
  assert_eq!(merged_root_directory.files.len(), 0);
  assert_eq!(merged_root_directory.directories.len(), 1);

  let merged_child_dirnode = merged_root_directory.directories[0].clone();
  let merged_child_dirnode_digest: Result<Digest, String> =
    merged_child_dirnode.get_digest().into();
  let merged_child_directory = runtime
    .block_on(store.load_directory(merged_child_dirnode_digest.unwrap(), WorkUnitStore::new()))
    .unwrap()
    .unwrap()
    .0;

  assert_eq!(merged_child_dirnode.name, common_dir_name);
  assert_eq!(
    merged_child_directory
      .files
      .iter()
      .map(|filenode| filenode.name.clone())
      .collect::<Vec<_>>(),
    vec!["roland".to_string(), "susannah".to_string()],
  );
}

#[test]
fn snapshot_merge_colliding() {
  let (store, tempdir, _, digester, runtime) = setup();

  let file = make_file_stat(
    tempdir.path(),
    &PathBuf::from("roland"),
    STR.as_bytes(),
    false,
  );

  let snapshot1 = runtime
    .block_on(Snapshot::from_path_stats(
      store.clone(),
      &digester,
      vec![file.clone()],
      WorkUnitStore::new(),
    ))
    .unwrap();

  let snapshot2 = runtime
    .block_on(Snapshot::from_path_stats(
      store.clone(),
      &digester,
      vec![file],
      WorkUnitStore::new(),
    ))
    .unwrap();

  let merged_res =
    Snapshot::merge(store.clone(), &[snapshot1, snapshot2], WorkUnitStore::new()).wait();

  match merged_res {
    Err(ref msg) if msg.contains("contained duplicate path") && msg.contains("roland") => (),
    x => panic!(
      "Snapshot::merge should have failed with a useful message; got: {:?}",
      x
    ),
  }
}

#[test]
fn strip_empty_prefix() {
  let (store, _, _, _, runtime) = setup();

  let dir = TestDirectory::nested();
  runtime
    .block_on(store.record_directory(&dir.directory(), false))
    .expect("Error storing directory");

  let result = runtime.block_on(super::Snapshot::strip_prefix(
    store,
    dir.digest(),
    PathBuf::from(""),
    WorkUnitStore::new(),
  ));
  assert_eq!(result, Ok(dir.digest()));
}

#[test]
fn strip_non_empty_prefix() {
  let (store, _, _, _, runtime) = setup();

  let dir = TestDirectory::nested();
  runtime
    .block_on(store.record_directory(&dir.directory(), false))
    .expect("Error storing directory");
  runtime
    .block_on(store.record_directory(&TestDirectory::containing_roland().directory(), false))
    .expect("Error storing directory");

  let result = runtime.block_on(super::Snapshot::strip_prefix(
    store,
    dir.digest(),
    PathBuf::from("cats"),
    WorkUnitStore::new(),
  ));
  assert_eq!(result, Ok(TestDirectory::containing_roland().digest()));
}

#[test]
fn strip_prefix_empty_subdir() {
  let (store, _, _, _, runtime) = setup();

  let dir = TestDirectory::containing_falcons_dir();
  runtime
    .block_on(store.record_directory(&dir.directory(), false))
    .expect("Error storing directory");

  let result = runtime.block_on(super::Snapshot::strip_prefix(
    store,
    dir.digest(),
    PathBuf::from("falcons/peregrine"),
    WorkUnitStore::new(),
  ));
  assert_eq!(result, Ok(TestDirectory::empty().digest()));
}

#[test]
fn strip_dir_not_in_store() {
  let (store, _, _, _, runtime) = setup();
  let digest = TestDirectory::nested().digest();
  let result = runtime.block_on(super::Snapshot::strip_prefix(
    store,
    digest,
    PathBuf::from("cats"),
    WorkUnitStore::new(),
  ));
  assert_eq!(result, Err(format!("{:?} was not known", digest)));
}

#[test]
fn strip_subdir_not_in_store() {
  let (store, _, _, _, runtime) = setup();
  let dir = TestDirectory::nested();
  runtime
    .block_on(store.record_directory(&dir.directory(), false))
    .expect("Error storing directory");
  let result = runtime.block_on(super::Snapshot::strip_prefix(
    store,
    dir.digest(),
    PathBuf::from("cats"),
    WorkUnitStore::new(),
  ));
  assert_eq!(
    result,
    Err(format!(
      "{:?} was not known",
      TestDirectory::containing_roland().digest()
    ))
  );
}

#[test]
fn strip_prefix_non_matching_file() {
  let (store, _, _, _, runtime) = setup();
  let dir = TestDirectory::recursive();
  let child_dir = TestDirectory::containing_roland();
  runtime
    .block_on(store.record_directory(&dir.directory(), false))
    .expect("Error storing directory");
  runtime
    .block_on(store.record_directory(&child_dir.directory(), false))
    .expect("Error storing directory");
  let result = runtime.block_on(super::Snapshot::strip_prefix(
    store,
    dir.digest(),
    PathBuf::from("cats"),
    WorkUnitStore::new(),
  ));

  assert_eq!(result, Err(format!("Cannot strip prefix cats from root directory {:?} - root directory contained non-matching file named: treats", dir.digest())));
}

#[test]
fn strip_prefix_non_matching_dir() {
  let (store, _, _, _, runtime) = setup();
  let dir = TestDirectory::double_nested_dir_and_file();
  let child_dir = TestDirectory::nested_dir_and_file();
  runtime
    .block_on(store.record_directory(&dir.directory(), false))
    .expect("Error storing directory");
  runtime
    .block_on(store.record_directory(&child_dir.directory(), false))
    .expect("Error storing directory");
  let result = runtime.block_on(super::Snapshot::strip_prefix(
    store,
    dir.digest(),
    PathBuf::from("animals/cats"),
    WorkUnitStore::new(),
  ));

  assert_eq!(result, Err(format!("Cannot strip prefix animals/cats from root directory {:?} - subdirectory animals contained non-matching directory named: birds", dir.digest())));
}

#[test]
fn strip_subdir_not_in_dir() {
  let (store, _, _, _, runtime) = setup();
  let dir = TestDirectory::nested();
  runtime
    .block_on(store.record_directory(&dir.directory(), false))
    .expect("Error storing directory");
  runtime
    .block_on(store.record_directory(&TestDirectory::containing_roland().directory(), false))
    .expect("Error storing directory");
  let result = runtime.block_on(super::Snapshot::strip_prefix(
    store,
    dir.digest(),
    PathBuf::from("cats/ugly"),
    WorkUnitStore::new(),
  ));
  assert_eq!(result, Err(format!("Cannot strip prefix cats/ugly from root directory {:?} - subdirectory cats didn't contain a directory named ugly but did contain file named: roland", dir.digest())));
}

fn make_dir_stat(root: &Path, relpath: &Path) -> PathStat {
  std::fs::create_dir(root.join(relpath)).unwrap();
  PathStat::dir(relpath.to_owned(), Dir(relpath.to_owned()))
}

fn make_file_stat(root: &Path, relpath: &Path, contents: &[u8], is_executable: bool) -> PathStat {
  make_file(
    &root.join(relpath),
    contents,
    if is_executable { 0o555 } else { 0o444 },
  );
  PathStat::file(
    relpath.to_owned(),
    File {
      path: relpath.to_owned(),
      is_executable,
    },
  )
}

fn expand_all_sorted(posix_fs: Arc<PosixFS>, executor: &task_executor::Executor) -> Vec<PathStat> {
  let mut v = executor
    .block_on(
      posix_fs.expand(
        // Don't error or warn if there are no paths matched -- that is a valid state.
        PathGlobs::create(
          &["**".to_owned()],
          StrictGlobMatching::Ignore,
          GlobExpansionConjunction::AllMatch,
        )
        .unwrap(),
      ),
    )
    .unwrap();
  v.sort_by(|a, b| a.path().cmp(b.path()));
  v
}
