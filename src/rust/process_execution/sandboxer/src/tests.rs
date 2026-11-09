// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use ::fs::{DigestTrie, DirectoryDigest, TypedPath};
use hashing::Digest;
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use tempfile::TempDir;
use tonic::Code;

use crate::test_util::prep_store;
use crate::{SandboxerClient, SandboxerService, ensure_socket_file_removed};

#[test]
fn test_ensure_socket_file_removed() {
    let dir = TempDir::new().unwrap();
    let subdir = dir.path().join("subdir");
    fs::create_dir(&subdir).unwrap();
    let socket_path = subdir.join("socket");

    // No-op if the socket_path doesn't exist.
    assert!(!fs::exists(&socket_path).unwrap());
    assert_eq!(Ok(()), ensure_socket_file_removed(&socket_path));
    assert!(!fs::exists(&socket_path).unwrap());

    // Fail if it exists but can't be deleted (because we lack write perms on the enclosing dir).
    let mut file = fs::File::create(&socket_path).unwrap();
    file.write(b"SOME CONTENT").unwrap();
    file.flush().unwrap();
    assert!(fs::exists(&socket_path).unwrap());
    fs::set_permissions(&subdir, fs::Permissions::from_mode(0o644)).unwrap();
    assert_eq!(
        Err("Permission denied (os error 13)".to_string()),
        ensure_socket_file_removed(&socket_path)
    );
    fs::set_permissions(&subdir, fs::Permissions::from_mode(0o755)).unwrap();

    // Succeed in deleting otherwise.
    assert!(fs::exists(&socket_path).unwrap());
    assert_eq!(Ok(()), ensure_socket_file_removed(&socket_path));
    assert!(!fs::exists(&socket_path).unwrap());
}

#[tokio::test]
async fn test_sandboxer_service() {
    // Tests the GRPC client and server by running all in-process,
    // without the process management wrapping.
    let dir = TempDir::new().unwrap();
    let dir_path = dir.path();
    let (store_cli_opt, dir_digest) = prep_store(dir_path).await;
    let socket_path = dir_path.join("sandboxer.sock");
    let sandbox_path = dir_path.join("sandbox");

    let mut sandboxer_service = SandboxerService::new(socket_path.clone(), store_cli_opt, None);
    tokio::spawn(async move { sandboxer_service.serve().await.unwrap() });

    let mut client = SandboxerClient::connect_with_retries(&socket_path)
        .await
        .unwrap();
    let res = client
        .materialize_directory(
            &sandbox_path,
            &sandbox_path,
            &DirectoryDigest::from_persisted_digest(dir_digest.as_digest()),
            &[],
        )
        .await;
    assert_eq!(Ok(()), res);

    let materialized_content =
        fs::read_to_string(sandbox_path.join("subdir").join("greeting.txt")).unwrap();
    assert_eq!("Hello, world!", materialized_content);
}

#[tokio::test]
async fn test_sandboxer_service_missing_digest() {
    let dir = TempDir::new().unwrap();
    let dir_path = dir.path();
    let (store_cli_opt, _) = prep_store(dir_path).await;
    let socket_path = dir_path.join("sandboxer.sock");
    let sandbox_path = dir_path.join("sandbox");

    let dir_digest = {
        let store = store_cli_opt
            .create_store(task_executor::Executor::new())
            .await
            .unwrap();
        let file_digests = HashMap::from([(
            PathBuf::from("missing.txt"),
            Digest::of_bytes(b"not in the store"),
        )]);
        let tree = DigestTrie::from_unique_paths(
            vec![TypedPath::File {
                path: Path::new("missing.txt"),
                is_executable: false,
            }],
            &file_digests,
        )
        .unwrap();
        store.record_digest_trie(tree, true).await.unwrap()
    };

    let mut sandboxer_service = SandboxerService::new(socket_path.clone(), store_cli_opt, None);
    tokio::spawn(async move { sandboxer_service.serve().await.unwrap() });

    let mut client = SandboxerClient::connect_with_retries(&socket_path)
        .await
        .unwrap();
    let status = client
        .request_materialize_directory(
            &sandbox_path,
            &sandbox_path,
            &DirectoryDigest::from_persisted_digest(dir_digest.as_digest()),
            &[],
        )
        .await
        .unwrap_err();

    assert_eq!(Code::NotFound, status.code(), "{status:?}");
}
