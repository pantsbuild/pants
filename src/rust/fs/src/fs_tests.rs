// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Tests for `FS`, which is `FS` on unix and `WinFS` on Windows. Where the platforms
// legitimately differ, the expected values come from the helpers at the bottom of this file.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use hashing::EMPTY_DIGEST;

use crate::FS;
use crate::testutil::make_file;
use crate::{
    DigestTrie, Dir, DirectoryListing, File, GitignoreStyleExcludes, GlobExpansionConjunction,
    GlobMatching, Link, PathGlobs, PathMetadataKind, PathStat, Stat, StrictGlobMatching,
    SymlinkBehavior, TypedPath,
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
    make_file(&dir.path().join("photograph_marmosets.exe"), &[], 0o700);
    assert_only_file_is_executable(dir.path(), true).await;
}

// On unix only the mode matters, not the extension.
#[cfg(unix)]
#[tokio::test]
async fn is_executable_ignores_extension() {
    let dir = tempfile::TempDir::new().unwrap();
    make_file(&dir.path().join("marmosets.exe"), &[], 0o600);
    assert_only_file_is_executable(dir.path(), false).await;
}

// On Windows only the extension matters, not the mode, and the extension is case-insensitive.
#[cfg(windows)]
#[tokio::test]
async fn is_executable_by_extension() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs(dir.path());
    // NB: The names must differ case-insensitively, since Windows filenames are case-insensitive.
    for (name, want_is_executable) in [
        ("no_extension", false),
        ("script.sh", false),
        ("script.py", false),
        ("program.exe", true),
        ("upper.EXE", true),
        ("program.com", true),
        ("mixed.Bat", true),
        ("script.cmd", true),
        ("program.exe.txt", false),
    ] {
        make_file(&dir.path().join(name), &[], 0o700);
        assert_eq!(
            fs.stat_sync(Path::new(name)).unwrap().unwrap(),
            Stat::File(File {
                path: PathBuf::from(name),
                is_executable: want_is_executable,
            }),
            "{name}"
        );
    }
}

#[tokio::test]
async fn file_path() {
    let dir = tempfile::TempDir::new().unwrap();
    let path = PathBuf::from("marmosets");
    let fs = new_fs(dir.path());
    // NB: On unix, `dunce::canonicalize` is just `std::fs::canonicalize`.
    let expected_path = dunce::canonicalize(dir.path()).unwrap().join(&path);
    let actual_path = fs.file_path(&File {
        path: path,
        is_executable: false,
    });
    assert_eq!(actual_path, expected_path);
    #[cfg(windows)]
    assert!(
        !actual_path.to_str().unwrap().starts_with(r"\\?\"),
        "{actual_path:?}"
    );
}

#[tokio::test]
async fn stat_executable_file() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs(dir.path());
    let path = PathBuf::from("photograph_marmosets.exe");
    make_file(&dir.path().join(&path), &[], 0o700);
    assert_eq!(
        fs.stat_sync(&path).unwrap().unwrap(),
        super::Stat::File(File {
            path: path,
            is_executable: true,
        })
    )
}

#[tokio::test]
async fn stat_nonexecutable_file() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs(dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);
    assert_eq!(
        fs.stat_sync(&path).unwrap().unwrap(),
        super::Stat::File(File {
            path: path,
            is_executable: false,
        })
    )
}

#[tokio::test]
async fn stat_dir() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs(dir.path());
    let path = PathBuf::from("enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();
    assert_eq!(
        fs.stat_sync(&path).unwrap().unwrap(),
        super::Stat::Dir(Dir(path))
    )
}

#[tokio::test]
async fn stat_symlink() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs(dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);

    let link_path = PathBuf::from("remarkably_similar_marmoset");
    symlink_file(dir.path().join(path.clone()), dir.path().join(&link_path));
    assert_eq!(
        fs.stat_sync(&link_path).unwrap().unwrap(),
        super::Stat::Link(Link {
            path: link_path,
            target: dir.path().join(path)
        })
    )
}

#[tokio::test]
async fn stat_symlink_oblivious() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs_symlink_oblivious(dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);

    let link_path = PathBuf::from("remarkably_similar_marmoset");
    symlink_file(dir.path().join(path), dir.path().join(&link_path));
    // Symlink oblivious stat will give us the destination type.
    assert_eq!(
        fs.stat_sync(&link_path).unwrap().unwrap(),
        super::Stat::File(File {
            path: link_path,
            is_executable: false,
        })
    )
}

// There is no Windows equivalent of a device file inside a directory.
#[cfg(unix)]
#[tokio::test]
async fn stat_other() {
    assert_eq!(new_fs("/dev").stat_sync(Path::new("null")).unwrap(), None,);
}

#[tokio::test]
async fn stat_missing() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs(dir.path());
    assert_eq!(fs.stat_sync(Path::new("no_marmosets")).unwrap(), None,);
}

#[tokio::test]
async fn scandir_empty() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs(dir.path());
    let path = PathBuf::from("empty_enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();
    assert_eq!(
        fs.scandir(Dir(path)).await.unwrap(),
        DirectoryListing(vec![])
    );
}

#[tokio::test]
async fn scandir() {
    let dir = tempfile::TempDir::new().unwrap();
    let path = PathBuf::from("enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();

    let a_marmoset = PathBuf::from("a_marmoset");
    let feed = PathBuf::from("feed.exe");
    let hammock = PathBuf::from("hammock");
    let remarkably_similar_marmoset = PathBuf::from("remarkably_similar_marmoset");
    let sneaky_marmoset = PathBuf::from("sneaky_marmoset");

    make_file(&dir.path().join(&path).join(&feed), &[], 0o700);
    make_file(&dir.path().join(&path).join(&a_marmoset), &[], 0o600);
    make_file(&dir.path().join(&path).join(&sneaky_marmoset), &[], 0o600);
    symlink_file(
        dir.path().join(&path).join(&a_marmoset),
        dir.path().join(&path).join(&remarkably_similar_marmoset),
    );
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
        new_fs(dir.path()).scandir(Dir(path.clone())).await.unwrap(),
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
        new_fs_symlink_oblivious(dir.path())
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
    let fs = new_fs(dir.path());
    fs.scandir(Dir(PathBuf::from("no_marmosets_here")))
        .await
        .expect_err("Want error");
}

#[tokio::test]
async fn stats_for_paths() {
    let dir = tempfile::TempDir::new().unwrap();
    let root_path = dir.path();

    // File tree:
    // dir
    // dir/recursive_symlink -> ../symlink -> executable_file.exe
    // dir_symlink -> dir
    // executable_file.exe
    // regular_file
    // symlink -> executable_file.exe
    // symlink_to_nothing -> doesnotexist

    make_file(&root_path.join("executable_file.exe"), &[], 0o700);
    make_file(&root_path.join("regular_file"), &[], 0o600);
    std::fs::create_dir(root_path.join("dir")).unwrap();
    symlink_file("executable_file.exe", root_path.join("symlink"));
    symlink_file(
        "../symlink",
        root_path.join("dir").join("recursive_symlink"),
    );
    symlink_dir("dir", root_path.join("dir_symlink"));
    symlink_file("doesnotexist", root_path.join("symlink_to_nothing"));

    let fs = Arc::new(new_fs(root_path));
    let path_stats = vec![
        PathBuf::from("executable_file.exe"),
        PathBuf::from("regular_file"),
        PathBuf::from("dir"),
        PathBuf::from("symlink"),
        PathBuf::from("dir").join("recursive_symlink"),
        PathBuf::from("dir_symlink"),
        PathBuf::from("symlink_to_nothing"),
        PathBuf::from("doesnotexist"),
    ]
    .into_iter()
    .map(|p| fs.stat_sync(&p).unwrap())
    .collect::<Vec<_>>();
    let v: Vec<Option<Stat>> = vec![
        Some(Stat::File(File {
            path: PathBuf::from("executable_file.exe"),
            is_executable: true,
        })),
        Some(Stat::File(File {
            path: PathBuf::from("regular_file"),
            is_executable: false,
        })),
        Some(Stat::Dir(Dir(PathBuf::from("dir")))),
        Some(Stat::Link(Link {
            path: PathBuf::from("symlink"),
            target: PathBuf::from("executable_file.exe"),
        })),
        Some(Stat::Link(Link {
            path: PathBuf::from("recursive_symlink"),
            target: native_path("../symlink"),
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

#[tokio::test]
async fn read_link() {
    let dir = tempfile::TempDir::new().unwrap();
    std::fs::create_dir_all(dir.path().join("a").join("b")).unwrap();
    make_file(&dir.path().join("a").join("b").join("marmoset"), &[], 0o600);
    // On Windows, `symlink_file` writes the target with `\\`, and FS reports it as-is.
    symlink_file("b/marmoset", dir.path().join("a").join("link"));

    let fs = new_fs(dir.path());
    let link = Link {
        path: PathBuf::from("a").join("link"),
        target: native_path("b/marmoset"),
    };
    let Stat::Link(stat) = fs.stat_sync(&link.path).unwrap().unwrap() else {
        panic!("Expected a link");
    };
    assert_eq!(stat.path, PathBuf::from("link"));
    // NB: `PathBuf` equality on Windows treats `/` and `\\` alike, so compare the raw strings.
    assert_eq!(
        stat.target.as_os_str(),
        native_path("b/marmoset").as_os_str()
    );
    assert_eq!(
        fs.read_link(&link).await.unwrap(),
        PathBuf::from("a").join("b").join("marmoset")
    );
}

#[tokio::test]
async fn read_link_rejects_absolute_target() {
    let dir = tempfile::TempDir::new().unwrap();
    make_file(&dir.path().join("marmoset"), &[], 0o600);
    symlink_file(dir.path().join("marmoset"), dir.path().join("link"));
    let fs = new_fs(dir.path());
    let err = fs
        .read_link(&Link {
            path: PathBuf::from("link"),
            target: dir.path().join("marmoset"),
        })
        .await
        .expect_err("Want error");
    assert_eq!(err.kind(), std::io::ErrorKind::InvalidData, "{err}");
}

// Targets that are not `Path::is_absolute` on Windows, but are not relative to the link either.
#[cfg(windows)]
#[tokio::test]
async fn read_link_rejects_rooted_and_prefixed_targets() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs(dir.path());
    for (name, target) in [("rooted", "\\marmosets"), ("drive_relative", "C:marmosets")] {
        symlink_file(target, dir.path().join(name));
        let link = Link {
            path: PathBuf::from(name),
            target: PathBuf::from(target),
        };
        let err = fs.read_link(&link).await.expect_err("Want error");
        assert_eq!(err.kind(), std::io::ErrorKind::InvalidData, "{name}: {err}");
    }
}

#[tokio::test]
async fn path_metadata() {
    let dir = tempfile::TempDir::new().unwrap();
    make_file(&dir.path().join("marmoset.exe"), b"marmoset", 0o700);
    symlink_file("marmoset.exe", dir.path().join("link"));
    let fs = new_fs(dir.path());

    let file = fs
        .path_metadata(PathBuf::from("marmoset.exe"), false)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(file.kind, PathMetadataKind::File);
    assert_eq!(file.length, 8);
    assert!(file.is_executable);
    assert_eq!(
        file.unix_mode.map(|mode| mode & 0o777),
        if cfg!(unix) { Some(0o700) } else { None }
    );

    let link = fs
        .path_metadata(PathBuf::from("link"), false)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(link.kind, PathMetadataKind::Symlink);
    assert_eq!(link.symlink_target, Some(PathBuf::from("marmoset.exe")));

    let followed = fs
        .path_metadata(PathBuf::from("link"), true)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(followed.kind, PathMetadataKind::File);

    for missing in ["no_marmosets", "marmoset.exe/under_a_file"] {
        assert_eq!(
            fs.path_metadata(PathBuf::from(missing), false)
                .await
                .unwrap(),
            None,
            "{missing}"
        );
    }
}

// `:` is legal in a POSIX filename, but not in a Windows one.
#[cfg(windows)]
#[tokio::test]
async fn path_metadata_illegal_filename() {
    let dir = tempfile::TempDir::new().unwrap();
    let fs = new_fs(dir.path());
    assert_eq!(
        fs.path_metadata(PathBuf::from("illegal:name"), false)
            .await
            .unwrap(),
        None
    );
}

#[cfg(windows)]
#[test]
fn relativize_junction_target() {
    use crate::winfs::relativize_junction_target;

    let root = Path::new(r"\\?\C:\repo");
    for (link_parent, target, expected) in [
        // Sibling, cousin, child and ancestor targets.
        (r"C:\repo\a", r"C:\repo\a\b", Some(r"b")),
        (r"C:\repo\a", r"C:\repo\b", Some(r"..\b")),
        (r"C:\repo\a\b", r"C:\repo\c\d", Some(r"..\..\c\d")),
        (r"C:\repo\a", r"C:\repo", Some(r"..")),
        (r"C:\repo\a", r"C:\repo\a", Some(r".")),
        // Verbatim and ordinary paths, and differently-cased paths, are equivalent.
        (r"\\?\C:\repo\a", r"c:\REPO\B", Some(r"..\B")),
        (r"C:\Repo\A", r"\\?\C:\repo\a\b", Some(r"b")),
        // `..` is resolved lexically.
        (r"C:\repo\a", r"C:\repo\x\..\b", Some(r"..\b")),
        // Targets outside the root.
        (r"C:\repo\a", r"C:\other", None),
        (r"C:\repo\a", r"C:\repository", None),
        (r"C:\repo\a", r"C:\repo\..\other", None),
        (r"C:\repo\a", r"D:\repo\b", None),
        (r"C:\repo\a", r"\\server\share\repo\b", None),
    ] {
        assert_eq!(
            relativize_junction_target(root, Path::new(link_parent), Path::new(target)),
            expected.map(PathBuf::from),
            "{link_parent} -> {target}"
        );
    }

    let unc_root = Path::new(r"\\?\UNC\Server\Share\repo");
    assert_eq!(
        relativize_junction_target(
            unc_root,
            Path::new(r"\\server\share\repo\a"),
            Path::new(r"\\SERVER\share\repo\b"),
        ),
        Some(PathBuf::from(r"..\b"))
    );
}

#[cfg(windows)]
#[tokio::test]
async fn junction_inside_root() {
    let dir = tempfile::TempDir::new().unwrap();
    std::fs::create_dir_all(dir.path().join("a")).unwrap();
    std::fs::create_dir_all(dir.path().join("b")).unwrap();
    make_file(&dir.path().join("b").join("marmoset"), &[], 0o600);
    junction(dir.path().join("b"), dir.path().join("a").join("j"));

    let fs = new_fs(dir.path());
    let link = Link {
        path: PathBuf::from("a").join("j"),
        target: PathBuf::from(r"..\b"),
    };
    let Stat::Link(stat) = fs.stat_sync(&link.path).unwrap().unwrap() else {
        panic!("Expected a link");
    };
    assert_eq!(stat.target.as_os_str(), r"..\b");
    assert_eq!(
        fs.read_link(&link).await.unwrap(),
        PathBuf::from("a").join("..").join("b")
    );
    let metadata = fs
        .path_metadata(link.path.clone(), false)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(metadata.kind, PathMetadataKind::Symlink);
    assert_eq!(metadata.symlink_target, Some(PathBuf::from(r"..\b")));
}

#[cfg(windows)]
#[tokio::test]
async fn junction_outside_root() {
    let outside = tempfile::TempDir::new().unwrap();
    let dir = tempfile::TempDir::new().unwrap();
    junction(outside.path(), dir.path().join("j"));

    let fs = new_fs(dir.path());
    let Stat::Link(stat) = fs.stat_sync(Path::new("j")).unwrap().unwrap() else {
        panic!("Expected a link");
    };
    assert!(stat.target.is_absolute(), "{:?}", stat.target);
    let err = fs.read_link(&stat).await.expect_err("Want error");
    assert_eq!(err.kind(), std::io::ErrorKind::InvalidData, "{err}");
}

async fn assert_only_file_is_executable(path: &Path, want_is_executable: bool) {
    let fs = new_fs(path);
    let stats = fs.scandir(Dir(PathBuf::from("."))).await.unwrap();
    assert_eq!(stats.0.len(), 1);
    match stats.0.first().unwrap() {
        &super::Stat::File(File {
            is_executable: got, ..
        }) => assert_eq!(want_is_executable, got),
        other => panic!("Expected file, got {other:?}"),
    }
}

fn new_fs<P: AsRef<Path>>(dir: P) -> FS {
    FS::new(
        dir.as_ref(),
        GitignoreStyleExcludes::empty(),
        task_executor::Executor::new(),
    )
    .unwrap()
}

fn new_fs_symlink_oblivious<P: AsRef<Path>>(dir: P) -> FS {
    FS::new_with_symlink_behavior(
        dir.as_ref(),
        GitignoreStyleExcludes::empty(),
        task_executor::Executor::new(),
        SymlinkBehavior::Oblivious,
    )
    .unwrap()
}

#[cfg(unix)]
fn symlink_file<P: AsRef<Path>, Q: AsRef<Path>>(target: P, link: Q) {
    std::os::unix::fs::symlink(target, link).unwrap();
}

#[cfg(unix)]
fn symlink_dir<P: AsRef<Path>, Q: AsRef<Path>>(target: P, link: Q) {
    std::os::unix::fs::symlink(target, link).unwrap();
}

// NB: Creating symlinks on Windows requires either Developer Mode or the SeCreateSymbolicLink
// privilege. Relative targets are written with `\\`, as `git` does when it checks out a symlink.
#[cfg(windows)]
fn symlink_file<P: AsRef<Path>, Q: AsRef<Path>>(target: P, link: Q) {
    let target = windows_link_target(target.as_ref());
    std::os::windows::fs::symlink_file(&target, link.as_ref()).unwrap_or_else(|e| {
        panic!(
            "Failed to create symlink {:?} -> {target:?}: {e}",
            link.as_ref()
        )
    });
}

#[cfg(windows)]
fn symlink_dir<P: AsRef<Path>, Q: AsRef<Path>>(target: P, link: Q) {
    let target = windows_link_target(target.as_ref());
    std::os::windows::fs::symlink_dir(&target, link.as_ref()).unwrap_or_else(|e| {
        panic!(
            "Failed to create symlink {:?} -> {target:?}: {e}",
            link.as_ref()
        )
    });
}

#[cfg(windows)]
fn windows_link_target(target: &Path) -> PathBuf {
    PathBuf::from(target.to_str().unwrap().replace('/', "\\"))
}

/// The path that a target written with `/` has once `symlink_file` creates it on this platform.
fn native_path(path: &str) -> PathBuf {
    PathBuf::from(path.replace('/', std::path::MAIN_SEPARATOR_STR))
}

// NB: Unlike symlinks, junctions can be created without any special privileges.
#[cfg(windows)]
fn junction<P: AsRef<Path>, Q: AsRef<Path>>(target: P, link: Q) {
    let status = std::process::Command::new("cmd")
        .arg("/C")
        .arg("mklink")
        .arg("/J")
        .arg(link.as_ref())
        .arg(target.as_ref())
        .status()
        .unwrap();
    assert!(
        status.success(),
        "Failed to create junction {:?} -> {:?}",
        link.as_ref(),
        target.as_ref()
    );
}
