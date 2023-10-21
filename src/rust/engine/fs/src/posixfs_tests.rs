// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::path::{Path, PathBuf};
use std::sync::Arc;

use hashing::EMPTY_DIGEST;
use testutil::make_file;

use crate::{
    DigestTrie, Dir, DirectoryListing, File, GitignoreStyleExcludes, GlobExpansionConjunction,
    GlobMatching, Link, PathGlobs, PathStat, PosixFS, Stat, StrictGlobMatching, SymlinkBehavior,
    TypedPath,
};

#[tokio::test]
async fn is_executable_false() {
    let dir = tempfile::TempDir::new().unwrap();
    make_file(&dir.path().join("marmosets"), &[], 0o611);
    assert_only_file_is_executable(dir.path(), false).await;
}

#[tokio::test]
async fn is_executable_true() {
    let dir = tempfile::TempDir::new().unwrap();
    make_file(&dir.path().join("photograph_marmosets"), &[], 0o700);
    assert_only_file_is_executable(dir.path(), true).await;
}

#[tokio::test]
async fn file_path() {
    let dir = tempfile::TempDir::new().unwrap();
    let path = PathBuf::from("marmosets");
    let fs = new_posixfs(dir.path());
    let expected_path = std::fs::canonicalize(dir.path()).unwrap().join(&path);
    let actual_path = fs.file_path(&File {
        path: path,
        is_executable: false,
    });
    assert_eq!(actual_path, expected_path);
}

#[tokio::test]
async fn stat_executable_file() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(dir.path());
    let path = PathBuf::from("photograph_marmosets");
    make_file(&dir.path().join(&path), &[], 0o700);
    assert_eq!(
        posix_fs.stat_sync(&path).unwrap().unwrap(),
        super::Stat::File(File {
            path: path,
            is_executable: true,
        })
    )
}

#[tokio::test]
async fn stat_nonexecutable_file() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);
    assert_eq!(
        posix_fs.stat_sync(&path).unwrap().unwrap(),
        super::Stat::File(File {
            path: path,
            is_executable: false,
        })
    )
}

#[tokio::test]
async fn stat_dir() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(dir.path());
    let path = PathBuf::from("enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();
    assert_eq!(
        posix_fs.stat_sync(&path).unwrap().unwrap(),
        super::Stat::Dir(Dir(path))
    )
}

#[tokio::test]
async fn stat_symlink() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);

    let link_path = PathBuf::from("remarkably_similar_marmoset");
    std::os::unix::fs::symlink(dir.path().join(path.clone()), dir.path().join(&link_path)).unwrap();
    assert_eq!(
        posix_fs.stat_sync(&link_path).unwrap().unwrap(),
        super::Stat::Link(Link {
            path: link_path,
            target: dir.path().join(path)
        })
    )
}

#[tokio::test]
async fn stat_symlink_oblivious() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs_symlink_oblivious(dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);

    let link_path = PathBuf::from("remarkably_similar_marmoset");
    std::os::unix::fs::symlink(dir.path().join(path), dir.path().join(&link_path)).unwrap();
    // Symlink oblivious stat will give us the destination type.
    assert_eq!(
        posix_fs.stat_sync(&link_path).unwrap().unwrap(),
        super::Stat::File(File {
            path: link_path,
            is_executable: false,
        })
    )
}

#[tokio::test]
async fn stat_other() {
    assert_eq!(
        new_posixfs("/dev").stat_sync(Path::new("null")).unwrap(),
        None,
    );
}

#[tokio::test]
async fn stat_missing() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(dir.path());
    assert_eq!(posix_fs.stat_sync(Path::new("no_marmosets")).unwrap(), None,);
}

#[tokio::test]
async fn scandir_empty() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(dir.path());
    let path = PathBuf::from("empty_enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();
    assert_eq!(
        posix_fs.scandir(Dir(path)).await.unwrap(),
        DirectoryListing(vec![])
    );
}

#[tokio::test]
async fn scandir() {
    let dir = tempfile::TempDir::new().unwrap();
    let path = PathBuf::from("enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();

    let a_marmoset = PathBuf::from("a_marmoset");
    let feed = PathBuf::from("feed");
    let hammock = PathBuf::from("hammock");
    let remarkably_similar_marmoset = PathBuf::from("remarkably_similar_marmoset");
    let sneaky_marmoset = PathBuf::from("sneaky_marmoset");

    make_file(&dir.path().join(&path).join(&feed), &[], 0o700);
    make_file(&dir.path().join(&path).join(&a_marmoset), &[], 0o600);
    make_file(&dir.path().join(&path).join(&sneaky_marmoset), &[], 0o600);
    std::os::unix::fs::symlink(
        dir.path().join(&path).join(&a_marmoset),
        dir.path().join(&path).join(&remarkably_similar_marmoset),
    )
    .unwrap();
    std::fs::create_dir(dir.path().join(&path).join(&hammock)).unwrap();
    make_file(
        &dir.path()
            .join(&path)
            .join(&hammock)
            .join("napping_marmoset"),
        &[],
        0o600,
    );

    // Symlink aware.
    assert_eq!(
        new_posixfs(dir.path())
            .scandir(Dir(path.clone()))
            .await
            .unwrap(),
        DirectoryListing(vec![
            Stat::File(File {
                path: a_marmoset.clone(),
                is_executable: false,
            }),
            Stat::File(File {
                path: feed.clone(),
                is_executable: true,
            }),
            Stat::Dir(Dir(hammock.clone())),
            Stat::Link(Link {
                path: remarkably_similar_marmoset.clone(),
                target: dir.path().join(&path).join(&a_marmoset)
            }),
            Stat::File(File {
                path: sneaky_marmoset.clone(),
                is_executable: false,
            }),
        ])
    );

    // Symlink oblivious.
    assert_eq!(
        new_posixfs_symlink_oblivious(dir.path())
            .scandir(Dir(path))
            .await
            .unwrap(),
        DirectoryListing(vec![
            Stat::File(File {
                path: a_marmoset,
                is_executable: false,
            }),
            Stat::File(File {
                path: feed,
                is_executable: true,
            }),
            Stat::Dir(Dir(hammock)),
            Stat::File(File {
                path: remarkably_similar_marmoset,
                is_executable: false,
            }),
            Stat::File(File {
                path: sneaky_marmoset,
                is_executable: false,
            }),
        ])
    );
}

#[tokio::test]
async fn scandir_missing() {
    let dir = tempfile::TempDir::new().unwrap();
    let posix_fs = new_posixfs(dir.path());
    posix_fs
        .scandir(Dir(PathBuf::from("no_marmosets_here")))
        .await
        .expect_err("Want error");
}

#[tokio::test]
async fn stats_for_paths() {
    let dir = tempfile::TempDir::new().unwrap();
    let root_path = dir.path();

    // File tree:
    // dir
    // dir/recursive_symlink -> ../symlink -> executable_file
    // dir_symlink -> dir
    // executable_file
    // regular_file
    // symlink -> executable_file
    // symlink_to_nothing -> doesnotexist

    make_file(&root_path.join("executable_file"), &[], 0o700);
    make_file(&root_path.join("regular_file"), &[], 0o600);
    std::fs::create_dir(root_path.join("dir")).unwrap();
    std::os::unix::fs::symlink("executable_file", root_path.join("symlink")).unwrap();
    std::os::unix::fs::symlink(
        "../symlink",
        root_path.join("dir").join("recursive_symlink"),
    )
    .unwrap();
    std::os::unix::fs::symlink("dir", root_path.join("dir_symlink")).unwrap();
    std::os::unix::fs::symlink("doesnotexist", root_path.join("symlink_to_nothing")).unwrap();

    let posix_fs = Arc::new(new_posixfs(root_path));
    let path_stats = vec![
        PathBuf::from("executable_file"),
        PathBuf::from("regular_file"),
        PathBuf::from("dir"),
        PathBuf::from("symlink"),
        PathBuf::from("dir").join("recursive_symlink"),
        PathBuf::from("dir_symlink"),
        PathBuf::from("symlink_to_nothing"),
        PathBuf::from("doesnotexist"),
    ]
    .into_iter()
    .map(|p| posix_fs.stat_sync(&p).unwrap())
    .collect::<Vec<_>>();
    let v: Vec<Option<Stat>> = vec![
        Some(Stat::File(File {
            path: PathBuf::from("executable_file"),
            is_executable: true,
        })),
        Some(Stat::File(File {
            path: PathBuf::from("regular_file"),
            is_executable: false,
        })),
        Some(Stat::Dir(Dir(PathBuf::from("dir")))),
        Some(Stat::Link(Link {
            path: PathBuf::from("symlink"),
            target: PathBuf::from("executable_file"),
        })),
        Some(Stat::Link(Link {
            path: PathBuf::from("recursive_symlink"),
            target: PathBuf::from("../symlink"),
        })),
        Some(Stat::Link(Link {
            path: PathBuf::from("dir_symlink"),
            target: PathBuf::from("dir"),
        })),
        Some(Stat::Link(Link {
            path: PathBuf::from("symlink_to_nothing"),
            target: PathBuf::from("doesnotexist"),
        })),
        None,
    ];
    assert_eq!(v, path_stats);
}

#[tokio::test]
async fn memfs_expand_basic() {
    // Create two files, with the effect that there is a nested directory for the longer path.
    let p1 = PathBuf::from("some/file");
    let p2 = PathBuf::from("some/other");
    let p3 = p2.join("file");

    let fs = DigestTrie::from_unique_paths(
        vec![
            TypedPath::File {
                path: &p1,
                is_executable: false,
            },
            TypedPath::File {
                path: &p3,
                is_executable: false,
            },
        ],
        &vec![(p1.clone(), EMPTY_DIGEST), (p3.clone(), EMPTY_DIGEST)]
            .into_iter()
            .collect(),
    )
    .unwrap();
    let globs = PathGlobs::new(
        vec!["some/*".into()],
        StrictGlobMatching::Ignore,
        GlobExpansionConjunction::AnyMatch,
    )
    .parse()
    .unwrap();

    assert_eq!(
        fs.expand_globs(globs, SymlinkBehavior::Oblivious, None)
            .await
            .unwrap(),
        vec![
            PathStat::file(
                p1.clone(),
                File {
                    path: p1,
                    is_executable: false,
                },
            ),
            PathStat::dir(p2.clone(), Dir(p2)),
        ],
    );
}

async fn assert_only_file_is_executable(path: &Path, want_is_executable: bool) {
    let fs = new_posixfs(path);
    let stats = fs.scandir(Dir(PathBuf::from("."))).await.unwrap();
    assert_eq!(stats.0.len(), 1);
    match stats.0.get(0).unwrap() {
        &super::Stat::File(File {
            is_executable: got, ..
        }) => assert_eq!(want_is_executable, got),
        other => panic!("Expected file, got {other:?}"),
    }
}

fn new_posixfs<P: AsRef<Path>>(dir: P) -> PosixFS {
    PosixFS::new(
        dir.as_ref(),
        GitignoreStyleExcludes::empty(),
        task_executor::Executor::new(),
    )
    .unwrap()
}

fn new_posixfs_symlink_oblivious<P: AsRef<Path>>(dir: P) -> PosixFS {
    PosixFS::new_with_symlink_behavior(
        dir.as_ref(),
        GitignoreStyleExcludes::empty(),
        task_executor::Executor::new(),
        SymlinkBehavior::Oblivious,
    )
    .unwrap()
}
