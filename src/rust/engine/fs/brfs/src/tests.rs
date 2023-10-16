use tempfile;
use testutil;

use crate::mount;
use hashing;
use store::Store;
use testutil::{
    data::{TestData, TestDirectory},
    file,
};

#[tokio::test]
async fn missing_digest() {
    let (store_dir, mount_dir) = make_dirs();

    let runtime = task_executor::Executor::new();

    let store =
        Store::local_only(runtime.clone(), store_dir.path()).expect("Error creating local store");

    let _fs = mount(mount_dir.path(), store, runtime).expect("Mounting");
    assert!(!&mount_dir
        .path()
        .join("digest")
        .join(digest_to_filepath(&TestData::roland().digest()))
        .exists());
}

#[tokio::test]
async fn read_file_by_digest() {
    let (store_dir, mount_dir) = make_dirs();
    let runtime = task_executor::Executor::new();

    let store =
        Store::local_only(runtime.clone(), store_dir.path()).expect("Error creating local store");

    let test_bytes = TestData::roland();

    store
        .store_file_bytes(test_bytes.bytes(), false)
        .await
        .expect("Storing bytes");

    let _fs = mount(mount_dir.path(), store, runtime).expect("Mounting");
    let file_path = mount_dir
        .path()
        .join("digest")
        .join(digest_to_filepath(&test_bytes.digest()));
    assert_eq!(test_bytes.bytes(), file::contents(&file_path));
    assert!(file::is_executable(&file_path));
}

#[tokio::test]
async fn list_directory() {
    let (store_dir, mount_dir) = make_dirs();
    let runtime = task_executor::Executor::new();

    let store =
        Store::local_only(runtime.clone(), store_dir.path()).expect("Error creating local store");

    let test_bytes = TestData::roland();
    let test_directory = TestDirectory::containing_roland();

    store
        .store_file_bytes(test_bytes.bytes(), false)
        .await
        .expect("Storing bytes");
    store
        .record_directory(&test_directory.directory(), false)
        .await
        .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store, runtime).expect("Mounting");
    let virtual_dir = mount_dir
        .path()
        .join("directory")
        .join(digest_to_filepath(&test_directory.digest()));
    assert_eq!(vec!["roland.ext"], file::list_dir(&virtual_dir));
}

#[tokio::test]
async fn read_file_from_directory() {
    let (store_dir, mount_dir) = make_dirs();
    let runtime = task_executor::Executor::new();

    let store =
        Store::local_only(runtime.clone(), store_dir.path()).expect("Error creating local store");

    let test_bytes = TestData::roland();
    let test_directory = TestDirectory::containing_roland();

    store
        .store_file_bytes(test_bytes.bytes(), false)
        .await
        .expect("Storing bytes");
    store
        .record_directory(&test_directory.directory(), false)
        .await
        .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store, runtime).expect("Mounting");
    let roland = mount_dir
        .path()
        .join("directory")
        .join(digest_to_filepath(&test_directory.digest()))
        .join("roland.ext");
    assert_eq!(test_bytes.bytes(), file::contents(&roland));
    assert!(!file::is_executable(&roland));
}

#[tokio::test]
async fn list_recursive_directory() {
    let (store_dir, mount_dir) = make_dirs();
    let runtime = task_executor::Executor::new();

    let store =
        Store::local_only(runtime.clone(), store_dir.path()).expect("Error creating local store");

    let test_bytes = TestData::roland();
    let treat_bytes = TestData::catnip();
    let test_directory = TestDirectory::containing_roland();
    let recursive_directory = TestDirectory::recursive();

    store
        .store_file_bytes(test_bytes.bytes(), false)
        .await
        .expect("Storing bytes");
    store
        .store_file_bytes(treat_bytes.bytes(), false)
        .await
        .expect("Storing bytes");
    store
        .record_directory(&test_directory.directory(), false)
        .await
        .expect("Storing directory");
    store
        .record_directory(&recursive_directory.directory(), false)
        .await
        .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store, runtime).expect("Mounting");
    let virtual_dir = mount_dir
        .path()
        .join("directory")
        .join(digest_to_filepath(&recursive_directory.digest()));
    assert_eq!(vec!["cats", "treats.ext"], file::list_dir(&virtual_dir));
    assert_eq!(
        vec!["roland.ext"],
        file::list_dir(&virtual_dir.join("cats"))
    );
}

#[tokio::test]
async fn read_file_from_recursive_directory() {
    let (store_dir, mount_dir) = make_dirs();
    let runtime = task_executor::Executor::new();

    let store =
        Store::local_only(runtime.clone(), store_dir.path()).expect("Error creating local store");

    let test_bytes = TestData::roland();
    let treat_bytes = TestData::catnip();
    let test_directory = TestDirectory::containing_roland();
    let recursive_directory = TestDirectory::recursive();

    store
        .store_file_bytes(test_bytes.bytes(), false)
        .await
        .expect("Storing bytes");
    store
        .store_file_bytes(treat_bytes.bytes(), false)
        .await
        .expect("Storing bytes");
    store
        .record_directory(&test_directory.directory(), false)
        .await
        .expect("Storing directory");
    store
        .record_directory(&recursive_directory.directory(), false)
        .await
        .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store, runtime).expect("Mounting");
    let virtual_dir = mount_dir
        .path()
        .join("directory")
        .join(digest_to_filepath(&recursive_directory.digest()));
    let treats = virtual_dir.join("treats.ext");
    assert_eq!(treat_bytes.bytes(), file::contents(&treats));
    assert!(!file::is_executable(&treats));

    let roland = virtual_dir.join("cats").join("roland.ext");
    assert_eq!(test_bytes.bytes(), file::contents(&roland));
    assert!(!file::is_executable(&roland));
}

#[tokio::test]
async fn files_are_correctly_executable() {
    let (store_dir, mount_dir) = make_dirs();
    let runtime = task_executor::Executor::new();

    let store =
        Store::local_only(runtime.clone(), store_dir.path()).expect("Error creating local store");

    let treat_bytes = TestData::catnip();
    let directory = TestDirectory::with_maybe_executable_files(true);

    store
        .store_file_bytes(treat_bytes.bytes(), false)
        .await
        .expect("Storing bytes");
    store
        .record_directory(&directory.directory(), false)
        .await
        .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store, runtime).expect("Mounting");
    let virtual_dir = mount_dir
        .path()
        .join("directory")
        .join(digest_to_filepath(&directory.digest()));
    assert_eq!(vec!["feed.ext", "food.ext"], file::list_dir(&virtual_dir));
    assert!(file::is_executable(&virtual_dir.join("feed.ext")));
    assert!(!file::is_executable(&virtual_dir.join("food.ext")));
}

pub fn digest_to_filepath(digest: &hashing::Digest) -> String {
    format!("{}-{}", digest.hash, digest.size_bytes)
}

pub fn make_dirs() -> (tempfile::TempDir, tempfile::TempDir) {
    let store_dir = tempfile::Builder::new().prefix("store").tempdir().unwrap();
    let mount_dir = tempfile::Builder::new().prefix("mount").tempdir().unwrap();
    (store_dir, mount_dir)
}
