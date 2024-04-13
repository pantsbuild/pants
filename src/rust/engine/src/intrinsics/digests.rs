// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::path::PathBuf;

use fs::{
    DigestTrie, DirectoryDigest, GlobMatching, PathStat, RelativePath, SymlinkBehavior, TypedPath,
};
use futures::future::{BoxFuture, FutureExt};
use hashing::{Digest, EMPTY_DIGEST};
use pyo3::{PyRef, Python};
use store::{SnapshotOps, SubsetParams};

use crate::context::Context;
use crate::externs;
use crate::externs::fs::{PyAddPrefix, PyFileDigest, PyMergeDigests, PyRemovePrefix};
use crate::nodes::{
    lift_directory_digest, unmatched_globs_additional_context, DownloadedFile, NodeResult, Snapshot,
};
use crate::python::{throw, Key, Value};
use crate::Failure;

pub(crate) fn directory_digest_to_digest_contents(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let digest = Python::with_gil(|py| {
            let py_digest = (*args[0]).as_ref(py);
            lift_directory_digest(py_digest)
        })?;

        let digest_contents = context.core.store().contents_for_directory(digest).await?;

        Ok(Python::with_gil(|py| {
            Snapshot::store_digest_contents(py, &context, &digest_contents)
        })?)
    }
    .boxed()
}

pub(crate) fn directory_digest_to_digest_entries(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let digest = Python::with_gil(|py| {
            let py_digest = (*args[0]).as_ref(py);
            lift_directory_digest(py_digest)
        })?;
        let digest_entries = context.core.store().entries_for_directory(digest).await?;
        Ok(Python::with_gil(|py| {
            Snapshot::store_digest_entries(py, &context, &digest_entries)
        })?)
    }
    .boxed()
}

pub(crate) fn remove_prefix_request_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let (digest, prefix) = Python::with_gil(|py| {
            let py_remove_prefix = (*args[0])
                .as_ref(py)
                .extract::<PyRef<PyRemovePrefix>>()
                .map_err(|e| throw(format!("{e}")))?;
            let prefix = RelativePath::new(&py_remove_prefix.prefix)
                .map_err(|e| throw(format!("The `prefix` must be relative: {e}")))?;
            let res: NodeResult<_> = Ok((py_remove_prefix.digest.clone(), prefix));
            res
        })?;
        let digest = context.core.store().strip_prefix(digest, &prefix).await?;
        Ok(Python::with_gil(|py| {
            Snapshot::store_directory_digest(py, digest)
        })?)
    }
    .boxed()
}

pub(crate) fn add_prefix_request_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let (digest, prefix) = Python::with_gil(|py| {
            let py_add_prefix = (*args[0])
                .as_ref(py)
                .extract::<PyRef<PyAddPrefix>>()
                .map_err(|e| throw(format!("{e}")))?;
            let prefix = RelativePath::new(&py_add_prefix.prefix)
                .map_err(|e| throw(format!("The `prefix` must be relative: {e}")))?;
            let res: NodeResult<(DirectoryDigest, RelativePath)> =
                Ok((py_add_prefix.digest.clone(), prefix));
            res
        })?;
        let digest = context.core.store().add_prefix(digest, &prefix).await?;
        Ok(Python::with_gil(|py| {
            Snapshot::store_directory_digest(py, digest)
        })?)
    }
    .boxed()
}

pub(crate) fn digest_to_snapshot(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    let store = context.core.store();
    async move {
        let digest = Python::with_gil(|py| {
            let py_digest = (*args[0]).as_ref(py);
            lift_directory_digest(py_digest)
        })?;
        let snapshot = store::Snapshot::from_digest(store, digest).await?;
        Ok(Python::with_gil(|py| {
            Snapshot::store_snapshot(py, snapshot)
        })?)
    }
    .boxed()
}

pub(crate) fn merge_digests_request_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    let core = &context.core;
    let store = core.store();
    async move {
        let digests = Python::with_gil(|py| {
            (*args[0])
                .as_ref(py)
                .extract::<PyRef<PyMergeDigests>>()
                .map(|py_merge_digests| py_merge_digests.0.clone())
                .map_err(|e| throw(format!("{e}")))
        })?;
        let digest = store.merge(digests).await?;
        Ok(Python::with_gil(|py| {
            Snapshot::store_directory_digest(py, digest)
        })?)
    }
    .boxed()
}

pub(crate) fn download_file_to_digest(
    context: Context,
    mut args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let key = Key::from_value(args.pop().unwrap()).map_err(Failure::from)?;
        let snapshot = context.get(DownloadedFile(key)).await?;
        Ok(Python::with_gil(|py| {
            Snapshot::store_directory_digest(py, snapshot.into())
        })?)
    }
    .boxed()
}

pub(crate) fn path_globs_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let path_globs = Python::with_gil(|py| {
            let py_path_globs = (*args[0]).as_ref(py);
            Snapshot::lift_path_globs(py_path_globs)
        })
        .map_err(|e| throw(format!("Failed to parse PathGlobs: {e}")))?;
        let snapshot = context.get(Snapshot::from_path_globs(path_globs)).await?;
        Ok(Python::with_gil(|py| {
            Snapshot::store_directory_digest(py, snapshot.into())
        })?)
    }
    .boxed()
}

pub(crate) fn path_globs_to_paths(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    let core = context.core.clone();
    async move {
        let path_globs = Python::with_gil(|py| {
            let py_path_globs = (*args[0]).as_ref(py);
            Snapshot::lift_path_globs(py_path_globs)
        })
        .map_err(|e| throw(format!("Failed to parse PathGlobs: {e}")))?;

        let path_globs = path_globs.parse().map_err(throw)?;
        let path_stats = context
            .expand_globs(
                path_globs,
                SymlinkBehavior::Oblivious,
                unmatched_globs_additional_context(),
            )
            .await?;

        Python::with_gil(|py| {
            let mut files = Vec::new();
            let mut dirs = Vec::new();
            for ps in path_stats.iter() {
                match ps {
                    PathStat::File { path, .. } => {
                        files.push(Snapshot::store_path(py, path)?);
                    }
                    PathStat::Link { path, .. } => {
                        panic!("Paths shouldn't be symlink-aware {path:?}");
                    }
                    PathStat::Dir { path, .. } => {
                        dirs.push(Snapshot::store_path(py, path)?);
                    }
                }
            }
            Ok(externs::unsafe_call(
                py,
                core.types.paths,
                &[
                    externs::store_tuple(py, files),
                    externs::store_tuple(py, dirs),
                ],
            ))
        })
    }
    .boxed()
}

enum CreateDigestItem {
    FileContent(RelativePath, bytes::Bytes, bool),
    FileEntry(RelativePath, Digest, bool),
    SymlinkEntry(RelativePath, PathBuf),
    Dir(RelativePath),
}

pub(crate) fn create_digest_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    let mut new_file_count = 0;

    let items: Vec<CreateDigestItem> = {
        Python::with_gil(|py| {
            let py_create_digest = (*args[0]).as_ref(py);
            externs::collect_iterable(py_create_digest)
                .unwrap()
                .into_iter()
                .map(|obj| {
                    let raw_path: String = externs::getattr(obj, "path").unwrap();
                    let path = RelativePath::new(PathBuf::from(raw_path)).unwrap();
                    if obj.hasattr("content").unwrap() {
                        let bytes = bytes::Bytes::from(
                            externs::getattr::<Vec<u8>>(obj, "content").unwrap(),
                        );
                        let is_executable: bool = externs::getattr(obj, "is_executable").unwrap();
                        new_file_count += 1;
                        CreateDigestItem::FileContent(path, bytes, is_executable)
                    } else if obj.hasattr("file_digest").unwrap() {
                        let py_file_digest: PyFileDigest =
                            externs::getattr(obj, "file_digest").unwrap();
                        let is_executable: bool = externs::getattr(obj, "is_executable").unwrap();
                        CreateDigestItem::FileEntry(path, py_file_digest.0, is_executable)
                    } else if obj.hasattr("target").unwrap() {
                        let target: String = externs::getattr(obj, "target").unwrap();
                        CreateDigestItem::SymlinkEntry(path, PathBuf::from(target))
                    } else {
                        CreateDigestItem::Dir(path)
                    }
                })
                .collect()
        })
    };

    let mut typed_paths: Vec<TypedPath> = Vec::with_capacity(items.len());
    let mut file_digests: HashMap<PathBuf, Digest> = HashMap::with_capacity(items.len());
    let mut items_to_store = Vec::with_capacity(new_file_count);

    for item in &items {
        match item {
            CreateDigestItem::FileContent(path, bytes, is_executable) => {
                let digest = Digest::of_bytes(bytes);
                items_to_store.push((digest.hash, bytes.clone()));
                typed_paths.push(TypedPath::File {
                    path,
                    is_executable: *is_executable,
                });
                file_digests.insert(path.to_path_buf(), digest);
            }
            CreateDigestItem::FileEntry(path, digest, is_executable) => {
                typed_paths.push(TypedPath::File {
                    path,
                    is_executable: *is_executable,
                });
                file_digests.insert(path.to_path_buf(), *digest);
            }
            CreateDigestItem::SymlinkEntry(path, target) => {
                typed_paths.push(TypedPath::Link { path, target });
                file_digests.insert(path.to_path_buf(), EMPTY_DIGEST);
            }
            CreateDigestItem::Dir(path) => {
                typed_paths.push(TypedPath::Dir(path));
                file_digests.insert(path.to_path_buf(), EMPTY_DIGEST);
            }
        }
    }

    let store = context.core.store();
    let trie = DigestTrie::from_unique_paths(typed_paths, &file_digests).unwrap();
    async move {
        store.store_file_bytes_batch(items_to_store, true).await?;
        Ok(Python::with_gil(|py| {
            Snapshot::store_directory_digest(py, trie.into())
        })?)
    }
    .boxed()
}

pub(crate) fn digest_subset_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    let store = context.core.store();
    async move {
        let (path_globs, original_digest) = Python::with_gil(|py| {
            let py_digest_subset = (*args[0]).as_ref(py);
            let py_path_globs = externs::getattr(py_digest_subset, "globs").unwrap();
            let py_digest = externs::getattr(py_digest_subset, "digest").unwrap();
            let res: NodeResult<_> = Ok((
                Snapshot::lift_prepared_path_globs(py_path_globs)?,
                lift_directory_digest(py_digest)?,
            ));
            res
        })?;
        let subset_params = SubsetParams { globs: path_globs };
        let digest = store.subset(original_digest, subset_params).await?;
        Ok(Python::with_gil(|py| {
            Snapshot::store_directory_digest(py, digest)
        })?)
    }
    .boxed()
}
