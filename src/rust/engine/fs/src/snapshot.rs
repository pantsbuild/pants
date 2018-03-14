// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

extern crate tempdir;

use bazel_protos;
use boxfuture::{BoxFuture, Boxable};
use bytes::Bytes;
use futures::Future;
use futures::future::join_all;
use hashing::{Digest, Fingerprint};
use itertools::Itertools;
use {File, FileContent, PathStat, Store};
use protobuf;
use std::collections::HashMap;
use std::ffi::OsString;
use std::fmt;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

const EMPTY_FINGERPRINT: Fingerprint = Fingerprint([
  0xe3, 0xb0, 0xc4, 0x42, 0x98, 0xfc, 0x1c, 0x14, 0x9a, 0xfb, 0xf4, 0xc8, 0x99, 0x6f, 0xb9, 0x24,
  0x27, 0xae, 0x41, 0xe4, 0x64, 0x9b, 0x93, 0x4c, 0xa4, 0x95, 0x99, 0x1b, 0x78, 0x52, 0xb8, 0x55,
]);
pub const EMPTY_DIGEST: Digest = Digest(EMPTY_FINGERPRINT, 0);

#[derive(Clone, Eq, Hash, PartialEq)]
pub struct Snapshot {
  pub digest: Digest,
  pub path_stats: Vec<PathStat>,
}

// StoreFileByDigest allows a File to be saved to an underlying Store, in such a way that it can be
// looked up by the Digest produced by the store_by_digest method.
// It is a separate trait so that caching implementations can be written which wrap the Store (used
// to store the bytes) and VFS (used to read the files off disk if needed).
pub trait StoreFileByDigest<Error> {
  fn store_by_digest(&self, file: &File) -> BoxFuture<Digest, Error>;
}

impl Snapshot {
  pub fn empty() -> Snapshot {
    Snapshot {
      digest: EMPTY_DIGEST,
      path_stats: vec![],
    }
  }

  pub fn from_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: S,
    path_stats: Vec<PathStat>,
  ) -> BoxFuture<Snapshot, String> {
    let mut sorted_path_stats = path_stats.clone();
    sorted_path_stats.sort_by(|a, b| a.path().cmp(b.path()));
    Snapshot::ingest_directory_from_sorted_path_stats(store, file_digester, sorted_path_stats)
      .map(|digest| Snapshot { digest, path_stats })
      .to_boxed()
  }

  fn ingest_directory_from_sorted_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: S,
    path_stats: Vec<PathStat>,
  ) -> BoxFuture<Digest, String> {
    let mut file_futures: Vec<BoxFuture<bazel_protos::remote_execution::FileNode, String>> =
      Vec::new();
    let mut dir_futures: Vec<BoxFuture<bazel_protos::remote_execution::DirectoryNode, String>> =
      Vec::new();

    for (first_component, group) in &path_stats
      .iter()
      .cloned()
      .group_by(|s| s.path().components().next().unwrap().as_os_str().to_owned())
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
                .store_by_digest(&stat)
                .map_err(|e| format!("{:?}", e))
                .and_then(move |digest| {
                  let mut file_node = bazel_protos::remote_execution::FileNode::new();
                  file_node.set_name(osstring_as_utf8(first_component)?);
                  file_node.set_digest((&digest).into());
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
                .record_directory(&bazel_protos::remote_execution::Directory::new(), true)
                .map(move |digest| {
                  let mut directory_node = bazel_protos::remote_execution::DirectoryNode::new();
                  directory_node.set_name(osstring_as_utf8(first_component).unwrap());
                  directory_node.set_digest((&digest).into());
                  directory_node
                })
                .to_boxed(),
            );
          }
        }
      } else {
        dir_futures.push(
          // TODO: Memoize this in the graph
          Snapshot::ingest_directory_from_sorted_path_stats(
            store.clone(),
            file_digester.clone(),
            paths_of_child_dir(path_group),
          ).and_then(move |digest| {
            let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
            dir_node.set_name(osstring_as_utf8(first_component)?);
            dir_node.set_digest((&digest).into());
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
        store.record_directory(&directory, true)
      })
      .to_boxed()
  }

  // Preserves the order of Snapshot's path_stats in its returned Vec.
  pub fn contents(self, store: Store) -> BoxFuture<Vec<FileContent>, String> {
    let contents = Arc::new(Mutex::new(HashMap::new()));
    let path_stats = self.path_stats;
    Snapshot::contents_for_directory_helper(self.digest, store, PathBuf::from(""), contents.clone())
      .map(move |_| {
        let mut contents = contents.lock().unwrap();
        let mut vec = Vec::new();
        for path in path_stats.iter().filter_map(|path_stat| match path_stat {
          &PathStat::File { ref path, .. } => Some(path.to_path_buf()),
          &PathStat::Dir { .. } => None,
        }) {
          match contents.remove(&path) {
            Some(content) => vec.push(FileContent { path, content }),
            None => {
              panic!(format!(
                "PathStat for {:?} was present in path_stats but missing from Snapshot contents",
                path
              ));
            }
          }
        }
        vec
      })
      .to_boxed()
  }

  // Assumes that all fingerprints it encounters are valid.
  fn contents_for_directory_helper(
    digest: Digest,
    store: Store,
    path_so_far: PathBuf,
    contents_wrapped: Arc<Mutex<HashMap<PathBuf, Bytes>>>,
  ) -> BoxFuture<(), String> {
    store
      .load_directory(digest)
      .and_then(move |maybe_dir| {
        maybe_dir.ok_or_else(|| format!("Could not find directory with digest {:?}", digest))
      })
      .and_then(move |dir| {
        let contents_wrapped_copy = contents_wrapped.clone();
        let path_so_far_copy = path_so_far.clone();
        let store_copy = store.clone();
        let file_futures = join_all(
          dir
            .get_files()
            .iter()
            .map(move |file_node| {
              let path = path_so_far_copy.join(file_node.get_name());
              let contents_wrapped_copy = contents_wrapped_copy.clone();
              store_copy
                .load_file_bytes_with(file_node.get_digest().into(), |b| b)
                .and_then(move |maybe_bytes| {
                  maybe_bytes
                    .ok_or_else(|| format!("Couldn't find file contents for {:?}", path))
                    .map(move |bytes| {
                      let mut contents = contents_wrapped_copy.lock().unwrap();
                      contents.insert(path, bytes);
                    })
                })
            })
            .collect::<Vec<_>>(),
        );
        let contents_wrapped_copy2 = contents_wrapped.clone();
        let store_copy = store.clone();
        let dir_futures = join_all(
          dir
            .get_directories()
            .iter()
            .map(move |dir_node| {
              Snapshot::contents_for_directory_helper(
                dir_node.get_digest().into(),
                store_copy.clone(),
                path_so_far.join(dir_node.get_name()),
                contents_wrapped_copy2.clone(),
              )
            })
            .collect::<Vec<_>>(),
        );
        file_futures.join(dir_futures)
      })
      .map(|(_, _)| ())
      .to_boxed()
  }
}

impl fmt::Debug for Snapshot {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
    write!(
      f,
      "Snapshot(digest={:?}, entries={})",
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
        PathStat::File { path, stat } => PathStat::File {
          path: path.iter().skip(1).collect(),
          stat: stat,
        },
        PathStat::Dir { path, stat } => PathStat::Dir {
          path: path.iter().skip(1).collect(),
          stat: stat,
        },
      })
    })
    .collect()
}

fn osstring_as_utf8(path: OsString) -> Result<String, String> {
  path
    .into_string()
    .map_err(|p| format!("{:?}'s file_name is not representable in UTF8", p))
}

#[cfg(test)]
mod tests {
  extern crate tempdir;
  extern crate testutil;

  use boxfuture::{BoxFuture, Boxable};
  use bytes::Bytes;
  use futures::future::Future;
  use hashing::{Digest, Fingerprint};
  use tempdir::TempDir;
  use self::testutil::make_file;

  use super::super::{File, FileContent, Path, PathGlobs, PathStat, PosixFS, ResettablePool,
                     Snapshot, Store, StoreFileByDigest, VFS};

  use std;
  use std::error::Error;
  use std::path::PathBuf;
  use std::sync::Arc;

  const AGGRESSIVE: &str = "Aggressive";
  const LATIN: &str = "Chaetophractus villosus";
  const STR: &str = "European Burmese";

  fn setup() -> (Store, TempDir, Arc<PosixFS>, FileSaver) {
    let pool = Arc::new(ResettablePool::new("test-pool-".to_string()));
    // TODO: Pass a remote CAS address through.
    let store = Store::local_only(TempDir::new("lmdb_store").unwrap(), pool.clone()).unwrap();
    let dir = TempDir::new("root").unwrap();
    let posix_fs = Arc::new(PosixFS::new(dir.path(), pool, vec![]).unwrap());
    let file_saver = FileSaver(store.clone(), posix_fs.clone());
    (store, dir, posix_fs, file_saver)
  }

  #[test]
  fn snapshot_one_file() {
    let (store, dir, posix_fs, digester) = setup();

    let file_name = PathBuf::from("roland");
    make_file(&dir.path().join(&file_name), STR.as_bytes(), 0o600);

    let path_stats = expand_all_sorted(posix_fs);
    assert_eq!(
      Snapshot::from_path_stats(store, digester, path_stats.clone())
        .wait()
        .unwrap(),
      Snapshot {
        digest: Digest(
          Fingerprint::from_hex_string(
            "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16",
          ).unwrap(),
          80,
        ),
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
    assert_eq!(
      Snapshot::from_path_stats(store, digester, path_stats.clone())
        .wait()
        .unwrap(),
      Snapshot {
        digest: Digest(
          Fingerprint::from_hex_string(
            "8b1a7ea04eaa2527b35683edac088bc826117b53b7ec6601740b55e20bce3deb",
          ).unwrap(),
          78,
        ),
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
    assert_eq!(
      Snapshot::from_path_stats(store, digester, unsorted_path_stats.clone())
        .wait()
        .unwrap(),
      Snapshot {
        digest: Digest(
          Fingerprint::from_hex_string(
            "fbff703bdaac62accf2ea5083bcfed89292073bf710ef9ad14d9298c637e777b",
          ).unwrap(),
          232,
        ),
        path_stats: unsorted_path_stats,
      }
    );
  }

  #[test]
  fn contents_for_one_file() {
    let (store, dir, posix_fs, digester) = setup();

    let file_name = PathBuf::from("roland");
    make_file(&dir.path().join(&file_name), STR.as_bytes(), 0o600);

    let contents = Snapshot::from_path_stats(store.clone(), digester, expand_all_sorted(posix_fs))
      .wait()
      .unwrap()
      .contents(store)
      .wait()
      .unwrap();
    assert_snapshot_contents(contents, vec![(&file_name, STR)]);
  }

  #[test]
  fn contents_for_files_in_multiple_directories() {
    let (store, dir, posix_fs, digester) = setup();

    let armadillos = PathBuf::from("armadillos");
    let armadillos_abs = dir.path().join(&armadillos);
    std::fs::create_dir_all(&armadillos_abs).unwrap();
    let amy = armadillos.join("amy");
    make_file(&dir.path().join(&amy), LATIN.as_bytes(), 0o600);
    let rolex = armadillos.join("rolex");
    make_file(&dir.path().join(&rolex), AGGRESSIVE.as_bytes(), 0o600);

    let cats = PathBuf::from("cats");
    let cats_abs = dir.path().join(&cats);
    std::fs::create_dir_all(&cats_abs).unwrap();
    let roland = cats.join("roland");
    make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

    let dogs = PathBuf::from("dogs");
    let dogs_abs = dir.path().join(&dogs);
    std::fs::create_dir_all(&dogs_abs).unwrap();

    let path_stats_sorted = expand_all_sorted(posix_fs);
    let mut path_stats_reversed = path_stats_sorted.clone();
    path_stats_reversed.reverse();
    {
      let snapshot =
        Snapshot::from_path_stats(store.clone(), digester.clone(), path_stats_reversed)
          .wait()
          .unwrap();
      let contents = snapshot.contents(store.clone()).wait().unwrap();
      assert_snapshot_contents(
        contents,
        vec![(&roland, STR), (&rolex, AGGRESSIVE), (&amy, LATIN)],
      );
    }
    {
      let contents = Snapshot::from_path_stats(store.clone(), digester, path_stats_sorted)
        .wait()
        .unwrap()
        .contents(store)
        .wait()
        .unwrap();
      assert_snapshot_contents(
        contents,
        vec![(&amy, LATIN), (&rolex, AGGRESSIVE), (&roland, STR)],
      );
    }
  }

  #[derive(Clone)]
  struct FileSaver(Store, Arc<PosixFS>);

  impl StoreFileByDigest<String> for FileSaver {
    fn store_by_digest(&self, file: &File) -> BoxFuture<Digest, String> {
      let file_copy = file.clone();
      let store = self.0.clone();
      self
        .1
        .clone()
        .read_file(&file)
        .map_err(move |err| format!("Error reading file {:?}: {}", file_copy, err.description()))
        .and_then(move |content| store.store_file_bytes(content.content, true))
        .to_boxed()
    }
  }

  fn expand_all_sorted(posix_fs: Arc<PosixFS>) -> Vec<PathStat> {
    let mut v = posix_fs
      .expand(PathGlobs::create(&["**".to_owned()], &[]).unwrap())
      .wait()
      .unwrap();
    v.sort_by(|a, b| a.path().cmp(b.path()));
    v
  }

  fn assert_snapshot_contents(contents: Vec<FileContent>, expected: Vec<(&Path, &str)>) {
    let expected_with_array: Vec<_> = expected
      .into_iter()
      .map(|(path, s)| (path.to_path_buf(), Bytes::from(s)))
      .collect();
    let got: Vec<_> = contents
      .into_iter()
      .map(|file_content| (file_content.path, file_content.content))
      .collect();
    assert_eq!(expected_with_array, got);
  }
}
