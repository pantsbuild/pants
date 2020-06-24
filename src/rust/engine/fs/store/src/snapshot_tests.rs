use std::convert::TryInto;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use hashing::{Digest, Fingerprint};
use tempfile;
use testutil::data::TestDirectory;
use testutil::make_file;
use tokio::runtime::Handle;

use crate::{OneOffStoreFileByDigest, Snapshot, Store};
use fs::{
  Dir, File, GitignoreStyleExcludes, GlobExpansionConjunction, GlobMatching, PathGlobs, PathStat,
  PosixFS, StrictGlobMatching,
};

const STR: &str = "European Burmese";

fn setup() -> (
  Store,
  tempfile::TempDir,
  Arc<PosixFS>,
  OneOffStoreFileByDigest,
) {
  let executor = task_executor::Executor::new(Handle::current());
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
  let ignorer = GitignoreStyleExcludes::create(vec![]).unwrap();
  let posix_fs = Arc::new(PosixFS::new(dir.path(), ignorer, executor).unwrap());
  let file_saver = OneOffStoreFileByDigest::new(store.clone(), posix_fs.clone());
  (store, dir, posix_fs, file_saver)
}

#[tokio::test]
async fn snapshot_one_file() {
  let (store, dir, posix_fs, digester) = setup();

  let file_name = PathBuf::from("roland");
  make_file(&dir.path().join(&file_name), STR.as_bytes(), 0o600);

  let path_stats = expand_all_sorted(posix_fs).await;
  let snapshot = Snapshot::from_path_stats(store, digester, path_stats.clone())
    .await
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

#[tokio::test]
async fn snapshot_recursive_directories() {
  let (store, dir, posix_fs, digester) = setup();

  let cats = PathBuf::from("cats");
  let roland = cats.join("roland");
  std::fs::create_dir_all(&dir.path().join(cats)).unwrap();
  make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

  let path_stats = expand_all_sorted(posix_fs).await;
  let snapshot = Snapshot::from_path_stats(store, digester, path_stats.clone())
    .await
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

#[tokio::test]
async fn snapshot_from_digest() {
  let (store, dir, posix_fs, digester) = setup();

  let cats = PathBuf::from("cats");
  let roland = cats.join("roland");
  std::fs::create_dir_all(&dir.path().join(cats)).unwrap();
  make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

  let path_stats = expand_all_sorted(posix_fs).await;
  let expected_snapshot = Snapshot::from_path_stats(store.clone(), digester, path_stats.clone())
    .await
    .unwrap();
  assert_eq!(
    expected_snapshot,
    Snapshot::from_digest(store, expected_snapshot.digest,)
      .await
      .unwrap()
  );
}

#[tokio::test]
async fn snapshot_recursive_directories_including_empty() {
  let (store, dir, posix_fs, digester) = setup();

  let cats = PathBuf::from("cats");
  let roland = cats.join("roland");
  let dogs = PathBuf::from("dogs");
  let llamas = PathBuf::from("llamas");
  std::fs::create_dir_all(&dir.path().join(&cats)).unwrap();
  std::fs::create_dir_all(&dir.path().join(&dogs)).unwrap();
  std::fs::create_dir_all(&dir.path().join(&llamas)).unwrap();
  make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

  let sorted_path_stats = expand_all_sorted(posix_fs).await;
  let mut unsorted_path_stats = sorted_path_stats.clone();
  unsorted_path_stats.reverse();
  assert_eq!(
    Snapshot::from_path_stats(store, digester, unsorted_path_stats.clone(),)
      .await
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

#[tokio::test]
async fn merge_directories_two_files() {
  let (store, _, _, _) = setup();

  let containing_roland = TestDirectory::containing_roland();
  let containing_treats = TestDirectory::containing_treats();

  store
    .record_directory(&containing_roland.directory(), false)
    .await
    .expect("Storing roland directory");
  store
    .record_directory(&containing_treats.directory(), false)
    .await
    .expect("Storing treats directory");

  let result = Snapshot::merge_directories(
    store,
    vec![containing_treats.digest(), containing_roland.digest()],
  )
  .await;

  assert_eq!(
    result,
    Ok(TestDirectory::containing_roland_and_treats().digest())
  );
}

#[tokio::test]
async fn merge_directories_clashing_files() {
  let (store, _, _, _) = setup();

  let containing_roland = TestDirectory::containing_roland();
  let containing_wrong_roland = TestDirectory::containing_wrong_roland();

  store
    .record_directory(&containing_roland.directory(), false)
    .await
    .expect("Storing roland directory");
  store
    .record_directory(&containing_wrong_roland.directory(), false)
    .await
    .expect("Storing wrong roland directory");

  let err = Snapshot::merge_directories(
    store,
    vec![containing_roland.digest(), containing_wrong_roland.digest()],
  )
  .await
  .expect_err("Want error merging");

  assert!(
    err.contains("roland"),
    "Want error message to contain roland but was: {}",
    err
  );
}

#[tokio::test]
async fn merge_directories_same_files() {
  let (store, _, _, _) = setup();

  let containing_roland = TestDirectory::containing_roland();
  let containing_roland_and_treats = TestDirectory::containing_roland_and_treats();

  store
    .record_directory(&containing_roland.directory(), false)
    .await
    .expect("Storing roland directory");
  store
    .record_directory(&containing_roland_and_treats.directory(), false)
    .await
    .expect("Storing treats directory");

  let result = Snapshot::merge_directories(
    store,
    vec![
      containing_roland.digest(),
      containing_roland_and_treats.digest(),
    ],
  )
  .await;

  assert_eq!(
    result,
    Ok(TestDirectory::containing_roland_and_treats().digest())
  );
}

#[tokio::test]
async fn snapshot_merge_two_files() {
  let (store, tempdir, _, digester) = setup();

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

  let snapshot1 = Snapshot::from_path_stats(
    store.clone(),
    digester.clone(),
    vec![dir.clone(), file1.clone()],
  )
  .await
  .unwrap();

  let snapshot2 =
    Snapshot::from_path_stats(store.clone(), digester, vec![dir.clone(), file2.clone()])
      .await
      .unwrap();

  let merged = Snapshot::merge(store.clone(), &[snapshot1, snapshot2])
    .await
    .unwrap();
  let merged_root_directory = store
    .load_directory(merged.digest)
    .await
    .unwrap()
    .unwrap()
    .0;

  assert_eq!(merged.path_stats, vec![dir, file1, file2]);
  assert_eq!(merged_root_directory.files.len(), 0);
  assert_eq!(merged_root_directory.directories.len(), 1);

  let merged_child_dirnode = merged_root_directory.directories[0].clone();
  let merged_child_dirnode_digest: Result<Digest, String> =
    merged_child_dirnode.get_digest().try_into();
  let merged_child_directory = store
    .load_directory(merged_child_dirnode_digest.unwrap())
    .await
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

#[tokio::test]
async fn snapshot_merge_colliding() {
  let (store, tempdir, _, digester) = setup();

  let file = make_file_stat(
    tempdir.path(),
    &PathBuf::from("roland"),
    STR.as_bytes(),
    false,
  );

  let snapshot1 = Snapshot::from_path_stats(store.clone(), digester.clone(), vec![file.clone()])
    .await
    .unwrap();

  let snapshot2 = Snapshot::from_path_stats(store.clone(), digester, vec![file])
    .await
    .unwrap();

  let merged_res = Snapshot::merge(store.clone(), &[snapshot1, snapshot2]).await;

  match merged_res {
    Err(ref msg) if msg.contains("contained duplicate path") && msg.contains("roland") => (),
    x => panic!(
      "Snapshot::merge should have failed with a useful message; got: {:?}",
      x
    ),
  }
}

#[tokio::test]
async fn strip_empty_prefix() {
  let (store, _, _, _) = setup();

  let dir = TestDirectory::nested();
  store
    .record_directory(&dir.directory(), false)
    .await
    .expect("Error storing directory");

  let result = super::Snapshot::strip_prefix(store, dir.digest(), PathBuf::from("")).await;
  assert_eq!(result, Ok(dir.digest()));
}

#[tokio::test]
async fn strip_non_empty_prefix() {
  let (store, _, _, _) = setup();

  let dir = TestDirectory::nested();
  store
    .record_directory(&dir.directory(), false)
    .await
    .expect("Error storing directory");
  store
    .record_directory(&TestDirectory::containing_roland().directory(), false)
    .await
    .expect("Error storing directory");

  let result = super::Snapshot::strip_prefix(store, dir.digest(), PathBuf::from("cats")).await;
  assert_eq!(result, Ok(TestDirectory::containing_roland().digest()));
}

#[tokio::test]
async fn strip_prefix_empty_subdir() {
  let (store, _, _, _) = setup();

  let dir = TestDirectory::containing_falcons_dir();
  store
    .record_directory(&dir.directory(), false)
    .await
    .expect("Error storing directory");

  let result =
    super::Snapshot::strip_prefix(store, dir.digest(), PathBuf::from("falcons/peregrine")).await;
  assert_eq!(result, Ok(TestDirectory::empty().digest()));
}

#[tokio::test]
async fn strip_dir_not_in_store() {
  let (store, _, _, _) = setup();
  let digest = TestDirectory::nested().digest();
  let result = super::Snapshot::strip_prefix(store, digest, PathBuf::from("cats")).await;
  assert_eq!(result, Err(format!("{:?} was not known", digest)));
}

#[tokio::test]
async fn strip_subdir_not_in_store() {
  let (store, _, _, _) = setup();
  let dir = TestDirectory::nested();
  store
    .record_directory(&dir.directory(), false)
    .await
    .expect("Error storing directory");
  let result = super::Snapshot::strip_prefix(store, dir.digest(), PathBuf::from("cats")).await;
  assert_eq!(
    result,
    Err(format!(
      "{:?} was not known",
      TestDirectory::containing_roland().digest()
    ))
  );
}

#[tokio::test]
async fn strip_prefix_non_matching_file() {
  let (store, _, _, _) = setup();
  let dir = TestDirectory::recursive();
  let child_dir = TestDirectory::containing_roland();
  store
    .record_directory(&dir.directory(), false)
    .await
    .expect("Error storing directory");
  store
    .record_directory(&child_dir.directory(), false)
    .await
    .expect("Error storing directory");
  let result = super::Snapshot::strip_prefix(store, dir.digest(), PathBuf::from("cats")).await;

  assert_eq!(result, Err(format!("Cannot strip prefix cats from root directory {:?} - root directory contained non-matching file named: treats", dir.digest())));
}

#[tokio::test]
async fn strip_prefix_non_matching_dir() {
  let (store, _, _, _) = setup();
  let dir = TestDirectory::double_nested_dir_and_file();
  let child_dir = TestDirectory::nested_dir_and_file();
  store
    .record_directory(&dir.directory(), false)
    .await
    .expect("Error storing directory");
  store
    .record_directory(&child_dir.directory(), false)
    .await
    .expect("Error storing directory");
  let result =
    super::Snapshot::strip_prefix(store, dir.digest(), PathBuf::from("animals/cats")).await;

  assert_eq!(result, Err(format!("Cannot strip prefix animals/cats from root directory {:?} - subdirectory animals contained non-matching directory named: birds", dir.digest())));
}

#[tokio::test]
async fn strip_subdir_not_in_dir() {
  let (store, _, _, _) = setup();
  let dir = TestDirectory::nested();
  store
    .record_directory(&dir.directory(), false)
    .await
    .expect("Error storing directory");
  store
    .record_directory(&TestDirectory::containing_roland().directory(), false)
    .await
    .expect("Error storing directory");
  let result = super::Snapshot::strip_prefix(store, dir.digest(), PathBuf::from("cats/ugly")).await;
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

async fn expand_all_sorted(posix_fs: Arc<PosixFS>) -> Vec<PathStat> {
  let mut v = posix_fs
    .expand(
      // Don't error or warn if there are no paths matched -- that is a valid state.
      PathGlobs::new(
        vec!["**".to_owned()],
        StrictGlobMatching::Ignore,
        GlobExpansionConjunction::AllMatch,
      )
      .parse()
      .unwrap(),
    )
    .await
    .unwrap();
  v.sort_by(|a, b| a.path().cmp(b.path()));
  v
}
