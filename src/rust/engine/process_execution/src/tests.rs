// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::DefaultHasher;
use std::collections::BTreeMap;
use std::fs::Permissions;
use std::hash::{Hash, Hasher};
use std::os::unix::fs::PermissionsExt;
use std::process::Stdio;
use std::time::Duration;

use fs::RelativePath;
use prost_types::Timestamp;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::ExecutedActionMetadata;
use tempfile::TempDir;
use workunit_store::RunId;

use crate::{
    make_wrapper_for_append_only_caches, CacheName, Platform, Process, ProcessExecutionEnvironment,
    ProcessExecutionStrategy, ProcessResultMetadata, ProcessResultSource,
};

#[test]
fn process_equality() {
    // TODO: Tests like these would be cleaner with the builder pattern for the rust-side Process API.

    let process_generator = |description: String, timeout: Option<Duration>| {
        let mut p = Process::new(vec![]);
        p.description = description;
        p.timeout = timeout;
        p
    };

    fn hash<Hashable: Hash>(hashable: &Hashable) -> u64 {
        let mut hasher = DefaultHasher::new();
        hashable.hash(&mut hasher);
        hasher.finish()
    }

    let a = process_generator("One thing".to_string(), Some(Duration::new(0, 0)));
    let b = process_generator("Another".to_string(), Some(Duration::new(0, 0)));
    let c = process_generator("One thing".to_string(), Some(Duration::new(5, 0)));
    let d = process_generator("One thing".to_string(), None);

    // Process should derive a PartialEq and Hash that ignores the description
    assert_eq!(a, b);
    assert_eq!(hash(&a), hash(&b));

    // ..but not other fields.
    assert_ne!(a, c);
    assert_ne!(hash(&a), hash(&c));

    // Absence of timeout is included in hash.
    assert_ne!(a, d);
    assert_ne!(hash(&a), hash(&d));
}

#[test]
fn process_result_metadata_to_and_from_executed_action_metadata() {
    let env = ProcessExecutionEnvironment {
        name: None,
        platform: Platform::Linux_x86_64,
        strategy: ProcessExecutionStrategy::Local,
    };
    let action_metadata = ExecutedActionMetadata {
        worker_start_timestamp: Some(Timestamp {
            seconds: 100,
            nanos: 20,
        }),
        worker_completed_timestamp: Some(Timestamp {
            seconds: 120,
            nanos: 50,
        }),
        ..ExecutedActionMetadata::default()
    };

    let converted_process_result: ProcessResultMetadata = ProcessResultMetadata::new_from_metadata(
        action_metadata,
        ProcessResultSource::Ran,
        env.clone(),
        RunId(0),
    );
    assert_eq!(
        converted_process_result,
        ProcessResultMetadata::new(
            Some(concrete_time::Duration::new(20, 30)),
            ProcessResultSource::Ran,
            env.clone(),
            RunId(0),
        )
    );

    // The conversion from `ExecutedActionMetadata` to `ProcessResultMetadata` is lossy.
    let restored_action_metadata: ExecutedActionMetadata = converted_process_result.into();
    assert_eq!(
        restored_action_metadata,
        ExecutedActionMetadata {
            worker_start_timestamp: Some(Timestamp {
                seconds: 0,
                nanos: 0,
            }),
            worker_completed_timestamp: Some(Timestamp {
                seconds: 20,
                nanos: 30,
            }),
            ..ExecutedActionMetadata::default()
        }
    );

    // The relevant metadata may be missing from either type.
    let empty = ProcessResultMetadata::new(None, ProcessResultSource::Ran, env.clone(), RunId(0));
    let action_metadata_missing: ProcessResultMetadata = ProcessResultMetadata::new_from_metadata(
        ExecutedActionMetadata::default(),
        ProcessResultSource::Ran,
        env,
        RunId(0),
    );
    assert_eq!(action_metadata_missing, empty);
    let process_result_missing: ExecutedActionMetadata = empty.into();
    assert_eq!(process_result_missing, ExecutedActionMetadata::default());
}

#[test]
fn process_result_metadata_time_saved_from_cache() {
    let env = ProcessExecutionEnvironment {
        name: None,
        platform: Platform::Linux_x86_64,
        strategy: ProcessExecutionStrategy::Local,
    };
    let mut metadata = ProcessResultMetadata::new(
        Some(concrete_time::Duration::new(5, 150)),
        ProcessResultSource::Ran,
        env.clone(),
        RunId(0),
    );
    metadata.update_cache_hit_elapsed(Duration::new(1, 100));
    assert_eq!(
        Duration::from(metadata.saved_by_cache.unwrap()),
        Duration::new(4, 50)
    );

    // If the cache lookup took more time than the process, we return 0.
    let mut metadata = ProcessResultMetadata::new(
        Some(concrete_time::Duration::new(1, 0)),
        ProcessResultSource::Ran,
        env.clone(),
        RunId(0),
    );
    metadata.update_cache_hit_elapsed(Duration::new(5, 0));
    assert_eq!(
        Duration::from(metadata.saved_by_cache.unwrap()),
        Duration::new(0, 0)
    );

    // If the original process time wasn't recorded, we can't compute the time saved.
    let mut metadata = ProcessResultMetadata::new(None, ProcessResultSource::Ran, env, RunId(0));
    metadata.update_cache_hit_elapsed(Duration::new(1, 100));
    assert_eq!(metadata.saved_by_cache, None);
}

#[tokio::test]
async fn test_make_wrapper_for_append_only_caches_success() {
    const CACHE_NAME: &str = "test_cache";
    const SUBDIR_NAME: &str = "a subdir"; // Space intentionally included to test shell quoting.

    let mut caches = BTreeMap::new();
    caches.insert(
        CacheName::new(CACHE_NAME.into()).unwrap(),
        RelativePath::new("foo").unwrap(),
    );

    let dummy_caches_base_path = TempDir::new().unwrap();
    let dummy_sandbox_path = TempDir::new().unwrap();
    tokio::fs::create_dir_all(dummy_sandbox_path.path().join(SUBDIR_NAME))
        .await
        .unwrap();

    let script_content = make_wrapper_for_append_only_caches(
        &caches,
        dummy_caches_base_path.path().to_str().unwrap(),
        Some(SUBDIR_NAME),
    )
    .unwrap();

    let script_path = dummy_sandbox_path.path().join("wrapper");
    tokio::fs::write(&script_path, script_content.as_bytes())
        .await
        .unwrap();
    tokio::fs::set_permissions(&script_path, Permissions::from_mode(0o755))
        .await
        .unwrap();

    let mut cmd = tokio::process::Command::new("./wrapper");
    cmd.args(&["/bin/sh", "-c", "echo xyzzy > file.txt"]);
    cmd.current_dir(dummy_sandbox_path.path());
    cmd.stdin(Stdio::null());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let child = cmd.spawn().unwrap();
    let output = child.wait_with_output().await.unwrap();
    if output.status.code() != Some(0) {
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        println!("stdout:{}\n\nstderr: {}", &stdout, &stderr);
        panic!("Wrapper script failed to run: {}", output.status);
    }

    let cache_dir_path = dummy_caches_base_path.path().join(CACHE_NAME);
    let cache_dir_metadata = tokio::fs::metadata(&cache_dir_path).await.unwrap();
    assert!(
        cache_dir_metadata.is_dir(),
        "`test_cache` directory exists in caches base path"
    );

    let cache_symlink_path = dummy_sandbox_path.path().join("foo");
    let cache_symlink_metadata = tokio::fs::symlink_metadata(&cache_symlink_path)
        .await
        .unwrap();
    assert!(
        cache_symlink_metadata.is_symlink(),
        "symlink to cache created in sandbox path"
    );
    let link_target = tokio::fs::read_link(&cache_symlink_path).await.unwrap();
    assert_eq!(&link_target, &cache_dir_path);

    let test_file_metadata =
        tokio::fs::metadata(dummy_sandbox_path.path().join(SUBDIR_NAME).join("file.txt"))
            .await
            .unwrap();
    assert!(
        test_file_metadata.is_file(),
        "script wrote a file into a sudirectory (since script changed the working directory)"
    );
}
