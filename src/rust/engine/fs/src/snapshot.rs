// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use bazel_protos;
use boxfuture::{Boxable, BoxFuture};
use futures::Future;
use futures::future::join_all;
use hashing::{Digest, Fingerprint};
use itertools::Itertools;
use {File, PathStat, Store};
use protobuf;
use std::ffi::OsString;
use std::fmt;
use std::sync::Arc;

#[derive(Clone, PartialEq)]
pub struct Snapshot {
  // TODO: In a follow-up commit, fingerprint will be removed, and digest will be made non-optional.
  // They both exist right now as a compatibility shim so that the tar-based code and
  // Directory-based code can peacefully co-exist.
  pub fingerprint: Fingerprint,
  pub digest: Option<Digest>,
  pub path_stats: Vec<PathStat>,
}

pub trait GetFileDigest<Error> {
  fn digest(&self, file: &File) -> BoxFuture<Digest, Error>;
}

impl Snapshot {
  pub fn from_path_stats<GFD: GetFileDigest<Error> + Sized, Error: fmt::Debug + 'static + Send>(
    store: Arc<Store>,
    file_digester: Arc<GFD>,
    mut path_stats: Vec<PathStat>,
  ) -> BoxFuture<Snapshot, String> {
    let mut file_futures: Vec<BoxFuture<bazel_protos::remote_execution::FileNode, String>> =
      Vec::new();
    let mut dir_futures: Vec<BoxFuture<bazel_protos::remote_execution::DirectoryNode, String>> =
      Vec::new();

    path_stats.sort_by(|a, b| a.path().cmp(b.path()));

    for (first_component, group) in
      &path_stats.iter().cloned().group_by(|s| {
        s.path().components().next().unwrap().as_os_str().to_owned()
      })
    {
      let mut path_group: Vec<PathStat> = group.collect();
      if path_group.len() == 1 && path_group.get(0).unwrap().path().components().count() == 1 {
        // Exactly one entry with exactly one component indicates either a file in this directory,
        // or an empty directory.
        // If the child is a non-empty directory, or a file therein, there must be multiple
        // PathStats with that prefix component, and we will handle that in the recursive
        // save_directory call.

        match path_group.pop().unwrap() {
          PathStat::File { ref stat, .. } => {
            let is_executable = stat.is_executable;
            file_futures.push(
              file_digester
                .clone()
                .digest(&stat)
                .map_err(|e| format!("{:?}", e))
                .and_then(move |digest| {
                  let mut file_node = bazel_protos::remote_execution::FileNode::new();
                  file_node.set_name(osstring_as_utf8(first_component)?);
                  file_node.set_digest(digest.into());
                  file_node.set_is_executable(is_executable);
                  Ok(file_node)
                })
                .to_boxed(),
            );
          }
          PathStat::Dir { .. } => {
            // Because there are no children of this Dir, it must be empty.
            dir_futures.push(
              store
                .record_directory(&bazel_protos::remote_execution::Directory::new())
                .map(move |digest| {
                  let mut directory_node = bazel_protos::remote_execution::DirectoryNode::new();
                  directory_node.set_name(osstring_as_utf8(first_component).unwrap());
                  directory_node.set_digest(digest.into());
                  directory_node
                })
                .to_boxed(),
            );
          }
        }
      } else {
        dir_futures.push(
          // TODO: Memoize this in the graph
          Snapshot::from_path_stats(
            store.clone(),
            file_digester.clone(),
            paths_of_child_dir(path_group),
          ).and_then(move |snapshot| {
            let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
            dir_node.set_name(osstring_as_utf8(first_component)?);
            dir_node.set_digest(snapshot.digest.unwrap().into());
            Ok(dir_node)
          })
            .to_boxed(),
        );
      }
    }
    join_all(dir_futures)
      .join(join_all(file_futures))
      .and_then(move |(dirs, files)| {
        let mut directory = bazel_protos::remote_execution::Directory::new();
        directory.set_directories(protobuf::RepeatedField::from_vec(dirs));
        directory.set_files(protobuf::RepeatedField::from_vec(files));
        store.record_directory(&directory).map(move |digest| {
          Snapshot {
            fingerprint: digest.0,
            digest: Some(digest),
            path_stats: path_stats,
          }
        })
      })
      .to_boxed()
  }
}

impl fmt::Debug for Snapshot {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
    write!(
      f,
      "Snapshot({}, digest={:?}, entries={})",
      self.fingerprint.to_hex(),
      self.digest,
      self.path_stats.len()
    )
  }
}

fn paths_of_child_dir(paths: Vec<PathStat>) -> Vec<PathStat> {
  paths
    .into_iter()
    .filter_map(|s| {
      if s.path().components().count() == 1 {
        return None;
      }
      Some(match s {
        PathStat::File { path, stat } => {
          PathStat::File {
            path: path.iter().skip(1).collect(),
            stat: stat,
          }
        }
        PathStat::Dir { path, stat } => {
          PathStat::Dir {
            path: path.iter().skip(1).collect(),
            stat: stat,
          }
        }
      })
    })
    .collect()
}

fn osstring_as_utf8(path: OsString) -> Result<String, String> {
  path.into_string().map_err(|p| {
    format!("{:?}'s file_name is not representable in UTF8", p)
  })
}

#[cfg(test)]
mod tests {
  extern crate testutil;
  extern crate tempdir;

  use boxfuture::{BoxFuture, Boxable};
  use futures::future::Future;
  use hashing::{Digest, Fingerprint};
  use tempdir::TempDir;
  use self::testutil::make_file;

  use super::super::{File, GetFileDigest, PathGlobs, PathStat, PosixFS, ResettablePool, Snapshot,
                     Store, VFS};

  use std;
  use std::error::Error;
  use std::path::PathBuf;
  use std::sync::Arc;

  const STR: &str = "European Burmese";

  fn setup() -> (Arc<Store>, TempDir, Arc<PosixFS>, Arc<FileSaver>) {
    let pool = Arc::new(ResettablePool::new("test-pool-".to_string()));
    // TODO: Pass a remote CAS address through.
    let store = Arc::new(
      Store::local_only(TempDir::new("lmdb_store").unwrap(), pool.clone()).unwrap(),
    );
    let dir = TempDir::new("root").unwrap();
    let posix_fs = Arc::new(PosixFS::new(dir.path(), pool, vec![]).unwrap());
    let digester = Arc::new(FileSaver(store.clone(), posix_fs.clone()));
    (store, dir, posix_fs, digester)
  }

  #[test]
  fn snapshot_one_file() {
    let (store, dir, posix_fs, digester) = setup();

    let file_name = PathBuf::from("roland");
    make_file(&dir.path().join(&file_name), STR.as_bytes(), 0o600);

    let path_stats = expand_all_sorted(posix_fs);
    // TODO: Inline when only used once
    let fingerprint = Fingerprint::from_hex_string(
      "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16",
    ).unwrap();
    assert_eq!(
      Snapshot::from_path_stats(store, digester, path_stats.clone())
        .wait()
        .unwrap(),
      Snapshot {
        fingerprint: fingerprint,
        digest: Some(Digest(fingerprint, 80)),
        path_stats: path_stats,
      }
    );
  }

  #[test]
  fn snapshot_recursive_directories() {
    let (store, dir, posix_fs, digester) = setup();

    let cats = PathBuf::from("cats");
    let roland = cats.join("roland");
    std::fs::create_dir_all(&dir.path().join(cats)).unwrap();
    make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

    let path_stats = expand_all_sorted(posix_fs);
    // TODO: Inline when only used once
    let fingerprint = Fingerprint::from_hex_string(
      "8b1a7ea04eaa2527b35683edac088bc826117b53b7ec6601740b55e20bce3deb",
    ).unwrap();
    assert_eq!(
      Snapshot::from_path_stats(store, digester, path_stats.clone())
        .wait()
        .unwrap(),
      Snapshot {
        fingerprint: fingerprint,
        digest: Some(Digest(fingerprint, 78)),
        path_stats: path_stats,
      }
    );
  }

  #[test]
  fn snapshot_recursive_directories_including_empty() {
    let (store, dir, posix_fs, digester) = setup();

    let cats = PathBuf::from("cats");
    let roland = cats.join("roland");
    let dogs = PathBuf::from("dogs");
    let llamas = PathBuf::from("llamas");
    std::fs::create_dir_all(&dir.path().join(&cats)).unwrap();
    std::fs::create_dir_all(&dir.path().join(&dogs)).unwrap();
    std::fs::create_dir_all(&dir.path().join(&llamas)).unwrap();
    make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

    let sorted_path_stats = expand_all_sorted(posix_fs);
    let mut unsorted_path_stats = sorted_path_stats.clone();
    unsorted_path_stats.reverse();
    // TODO: Inline when only used once
    let fingerprint = Fingerprint::from_hex_string(
      "fbff703bdaac62accf2ea5083bcfed89292073bf710ef9ad14d9298c637e777b",
    ).unwrap();
    assert_eq!(
      Snapshot::from_path_stats(store, digester, unsorted_path_stats)
        .wait()
        .unwrap(),
      Snapshot {
        fingerprint: fingerprint,
        digest: Some(Digest(fingerprint, 232)),
        path_stats: sorted_path_stats,
      }
    );
  }

  struct FileSaver(Arc<Store>, Arc<PosixFS>);

  impl GetFileDigest<String> for FileSaver {
    fn digest(&self, file: &File) -> BoxFuture<Digest, String> {
      let file_copy = file.clone();
      let store = self.0.clone();
      self
        .1
        .clone()
        .read_file(&file)
        .map_err(move |err| {
          format!("Error reading file {:?}: {}", file_copy, err.description())
        })
        .and_then(move |content| store.store_file_bytes(content.content))
        .to_boxed()
    }
  }

  fn expand_all_sorted(posix_fs: Arc<PosixFS>) -> Vec<PathStat> {
    let mut v = posix_fs
      .expand(PathGlobs::create(&["**".to_owned()], &vec![]).unwrap())
      .wait()
      .unwrap();
    v.sort_by(|a, b| a.path().cmp(b.path()));
    v
  }
}
