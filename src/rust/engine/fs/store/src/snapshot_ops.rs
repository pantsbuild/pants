// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::convert::From;
use std::fmt::{Debug, Display};
use std::iter::Iterator;

use async_trait::async_trait;
use bytes::BytesMut;
use fs::{
    directory, DigestTrie, DirectoryDigest, GlobMatching, PreparedPathGlobs, RelativePath,
    SymlinkBehavior, EMPTY_DIRECTORY_DIGEST,
};
use futures::future::{self, FutureExt};
use hashing::Digest;
use itertools::Itertools;
use log::log_enabled;

///
/// Parameters used to determine which files and directories to operate on within a parent snapshot.
///
#[derive(Debug, Clone)]
pub struct SubsetParams {
    pub globs: PreparedPathGlobs,
}

///
/// Given Digest(s) representing Directory instances, merge them recursively into a single
/// output Directory Digest.
///
/// If a file is present with the same name and contents multiple times, it will appear once.
/// If a file is present with the same name, but different contents, an error will be returned.
///
async fn merge_directories<T: SnapshotOps + 'static>(
    store: T,
    dir_digests: Vec<DirectoryDigest>,
) -> Result<DirectoryDigest, T::Error> {
    let trees = future::try_join_all(
        dir_digests
            .into_iter()
            .map(|dd| store.load_digest_trie(dd))
            .collect::<Vec<_>>(),
    )
    .await?;

    let tree = match DigestTrie::merge(trees) {
        Ok(tree) => tree,
        Err(merge_error) => {
            // TODO: Use https://doc.rust-lang.org/nightly/std/result/enum.Result.html#method.into_ok_or_err
            // once it is stable.
            let err_string = match render_merge_error(&store, merge_error).await {
                Ok(e) | Err(e) => e,
            };
            return Err(err_string.into());
        }
    };

    Ok(tree.into())
}

///
/// Render a directory::MergeError (or fail with a less specific error if some content cannot be
/// loaded).
///
async fn render_merge_error<T: SnapshotOps + 'static>(
    store: &T,
    err: directory::MergeError,
) -> Result<String, String> {
    let directory::MergeError::Duplicates {
        parent_path,
        files,
        directories,
        symlinks,
    } = err;
    let file_details_by_name = files
        .iter()
        .map(|file| async move {
            let digest: Digest = file.digest();
            let header = format!(
                "file digest={} size={}:\n\n",
                digest.hash, digest.size_bytes
            );

            let contents = store
                .load_file_bytes_with(digest, |bytes| {
                    const MAX_LENGTH: usize = 1024;
                    let content_length = bytes.len();
                    let mut bytes =
                        BytesMut::from(&bytes[0..std::cmp::min(content_length, MAX_LENGTH)]);
                    if content_length > MAX_LENGTH && !log_enabled!(log::Level::Debug) {
                        bytes.extend_from_slice(
                            format!(
                                "\n... TRUNCATED contents from {content_length}B to {MAX_LENGTH}B \
                  (Pass -ldebug to see full contents)."
                            )
                            .as_bytes(),
                        );
                    }
                    String::from_utf8_lossy(bytes.to_vec().as_slice()).to_string()
                })
                .await
                .unwrap_or_else(|_| "<could not load contents>".to_string());
            let detail = format!("{header}{contents}");
            let res: Result<_, String> = Ok((file.name().to_owned(), detail));
            res
        })
        .map(|f| f.boxed());
    let symlink_details_by_name = symlinks
        .iter()
        .map(|symlink| async move {
            let target = symlink.target();
            let detail = format!("symlink target={}:\n\n", target.to_str().unwrap());
            let res: Result<_, String> = Ok((symlink.name(), detail));
            res
        })
        .map(|f| f.boxed());
    let dir_details_by_name = directories
        .iter()
        .map(|dir| async move {
            let digest = dir.digest();
            let detail = format!("dir digest={} size={}:\n\n", digest.hash, digest.size_bytes);
            let res: Result<_, String> = Ok((dir.name().to_owned(), detail));
            res
        })
        .map(|f| f.boxed());

    let duplicate_details = async move {
        let details_by_name = future::try_join_all(
            file_details_by_name
                .chain(symlink_details_by_name)
                .chain(dir_details_by_name)
                .collect::<Vec<_>>(),
        )
        .await?
        .into_iter()
        .into_group_map();

        let enumerated_details =
            std::iter::Iterator::flatten(details_by_name.iter().filter_map(|(name, details)| {
                if details.len() > 1 {
                    Some(details.iter().enumerate().map(move |(index, detail)| {
                        format!("`{}`: {}.) {}", name, index + 1, detail)
                    }))
                } else {
                    None
                }
            }))
            .collect();

        let res: Result<Vec<String>, T::Error> = Ok(enumerated_details);
        res
    }
    .await
    .unwrap_or_else(|err| vec![format!("Failed to load contents for comparison: {err}")]);

    Ok(format!(
        "Can only merge Directories with no duplicates, but found {} duplicate entries in {}:\
      \n\n{}",
        duplicate_details.len(),
        parent_path.display(),
        duplicate_details.join("\n\n")
    ))
}

///
/// High-level operations to manipulate and merge `Digest`s.
///
/// These methods take care to avoid redundant work when traversing Directory protos. Prefer to use
/// these primitives to compose any higher-level snapshot operations elsewhere in the codebase.
///
#[async_trait]
pub trait SnapshotOps: Clone + Send + Sync + 'static {
    type Error: Send + Debug + Display + From<String>;

    async fn load_file_bytes_with<
        T: Send + 'static,
        F: Fn(&[u8]) -> T + Clone + Send + Sync + 'static,
    >(
        &self,
        digest: Digest,
        f: F,
    ) -> Result<T, Self::Error>;

    async fn load_digest_trie(&self, digest: DirectoryDigest) -> Result<DigestTrie, Self::Error>;

    ///
    /// Given N Snapshots, returns a new Snapshot that merges them.
    ///
    async fn merge(&self, digests: Vec<DirectoryDigest>) -> Result<DirectoryDigest, Self::Error> {
        merge_directories(self.clone(), digests).await
    }

    async fn add_prefix(
        &self,
        digest: DirectoryDigest,
        prefix: &RelativePath,
    ) -> Result<DirectoryDigest, Self::Error> {
        Ok(self
            .load_digest_trie(digest)
            .await?
            .add_prefix(prefix)?
            .into())
    }

    async fn strip_prefix(
        &self,
        digest: DirectoryDigest,
        prefix: &RelativePath,
    ) -> Result<DirectoryDigest, Self::Error> {
        Ok(self
            .load_digest_trie(digest)
            .await?
            .remove_prefix(prefix)?
            .into())
    }

    async fn subset(
        &self,
        directory_digest: DirectoryDigest,
        params: SubsetParams,
    ) -> Result<DirectoryDigest, Self::Error> {
        let input_tree = self.load_digest_trie(directory_digest.clone()).await?;
        let path_stats = input_tree
            .expand_globs(params.globs, SymlinkBehavior::Aware, None)
            .await
            .map_err(|err| format!("Error matching globs against {directory_digest:?}: {err}"))?;

        let mut files = HashMap::new();
        input_tree.walk(SymlinkBehavior::Oblivious, &mut |path, entry| match entry {
            directory::Entry::File(f) => {
                files.insert(path.to_owned(), f.digest());
            }
            directory::Entry::Symlink(_) => panic!("Unexpected symlink"),
            directory::Entry::Directory(_) => (),
        });

        Ok(
            DigestTrie::from_unique_paths(path_stats.iter().map(|p| p.into()).collect(), &files)?
                .into(),
        )
    }

    async fn create_empty_dir(&self, path: &RelativePath) -> Result<DirectoryDigest, Self::Error> {
        self.add_prefix(EMPTY_DIRECTORY_DIGEST.clone(), path).await
    }
}
