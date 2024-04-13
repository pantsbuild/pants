// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
// TODO: Write a bunch more syscall-y tests to test that each syscall for each file/directory type
// acts as we expect.

use super::mount;
use super::tests::digest_to_filepath;
use crate::tests::make_dirs;
use libc;
use std::ffi::CString;
use std::path::Path;
use store::Store;
use testutil::data::TestData;

#[tokio::test]
async fn read_file_by_digest_exact_bytes() {
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

    let path = mount_dir
        .path()
        .join("digest")
        .join(digest_to_filepath(&test_bytes.digest()));

    let mut buf = make_buffer(test_bytes.len());

    unsafe {
        let fd = libc::open(path_to_cstring(&path).as_ptr(), 0);
        assert!(fd > 0, "Bad fd {}", fd);
        let read_bytes = libc::read(fd, buf.as_mut_ptr() as *mut libc::c_void, buf.len());
        assert_eq!(test_bytes.len() as isize, read_bytes);
        assert_eq!(0, libc::close(fd));
    }

    assert_eq!(test_bytes.string(), String::from_utf8(buf).unwrap());
}

fn path_to_cstring(path: &Path) -> CString {
    CString::new(path.to_string_lossy().as_bytes().to_owned()).unwrap()
}

fn make_buffer(size: usize) -> Vec<u8> {
    let mut buf: Vec<u8> = Vec::new();
    buf.resize(size, 0);
    buf
}
