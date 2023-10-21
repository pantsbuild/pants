// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;

use crate::directory::{DigestTrie, Entry, Name, TypedPath};
use crate::MAX_LINK_DEPTH;
use hashing::EMPTY_DIGEST;
use std::path::{Path, PathBuf};

fn make_tree(path_stats: Vec<TypedPath>) -> DigestTrie {
    let mut file_digests = HashMap::new();
    file_digests.extend(
        path_stats
            .iter()
            .map(|path| (path.to_path_buf(), EMPTY_DIGEST)),
    );

    DigestTrie::from_unique_paths(path_stats, &file_digests).unwrap()
}

fn assert_entry_is_none(tree: &DigestTrie, path: &str) {
    assert!(tree.entry(Path::new(path)).unwrap().is_none());
}

fn assert_entry_is_some(tree: &DigestTrie, path: &str) {
    assert!(tree.entry(Path::new(path)).unwrap().is_some());
}

fn assert_entry_is_err(tree: &DigestTrie, path: &str) {
    assert!(tree.entry(Path::new(path)).is_err());
}

#[test]
fn entry_simple() {
    let tree = make_tree(vec![
        TypedPath::Link {
            path: Path::new("linkfile"),
            target: Path::new("dir/file.txt"),
        },
        TypedPath::File {
            path: Path::new("dir/file.txt"),
            is_executable: false,
        },
    ]);

    assert_entry_is_some(&tree, "dir/file.txt");
    assert_entry_is_some(&tree, "linkfile");
}

#[test]
fn entry_self_referencing_symlink() {
    let tree = make_tree(vec![
        TypedPath::Link {
            path: Path::new("self"),
            target: Path::new("."),
        },
        TypedPath::File {
            path: Path::new("file.txt"),
            is_executable: false,
        },
    ]);

    let assert_is_file = |path: &str| match tree.entry(Path::new(path)).unwrap().unwrap() {
        Entry::File(file) => assert_eq!(file.name(), Name::new("file.txt")),
        _ => assert!(false),
    };

    for n in 0..(MAX_LINK_DEPTH + 1) {
        let path = "".to_owned() + &"self/".repeat(n.into()) + "file.txt";
        assert_is_file(&path);
    }
}

#[test]
fn entry_self_referencing_symlink_subdir() {
    let tree = make_tree(vec![
        TypedPath::Link {
            path: Path::new("a/self"),
            target: Path::new("."),
        },
        TypedPath::File {
            path: Path::new("a/file.txt"),
            is_executable: false,
        },
    ]);

    let assert_is_file = |path: &str| match tree.entry(Path::new(path)).unwrap().unwrap() {
        Entry::File(file) => assert_eq!(file.name(), Name::new("file.txt")),
        _ => assert!(false),
    };

    let assert_is_a = |path: &str| match tree.entry(Path::new(path)).unwrap().unwrap() {
        Entry::Directory(dir) => assert_eq!(dir.name(), Name::new("a")),
        _ => assert!(false),
    };

    // Max link depth isn't relevant here because we'll always land at something "real".
    for n in 0..MAX_LINK_DEPTH + 2 {
        let dirpath = "a/".to_owned() + &"self/".repeat(n.into());
        assert_is_a(&dirpath);
        let path = dirpath + "file.txt";
        assert_is_file(&path);
    }
}

#[test]
fn entry_too_far_up() {
    let tree = make_tree(vec![
        TypedPath::Link {
            path: Path::new("up1"),
            target: Path::new(".."),
        },
        TypedPath::Link {
            path: Path::new("dir/up2"),
            target: Path::new("../.."),
        },
        TypedPath::Link {
            path: Path::new("dir/up2-self"),
            target: Path::new("../../."),
        },
        TypedPath::Link {
            path: Path::new("selfdir"),
            target: Path::new("."),
        },
        TypedPath::File {
            path: Path::new("file.txt"),
            is_executable: false,
        },
    ]);

    assert_entry_is_none(&tree, "up1");
    assert_entry_is_none(&tree, "dir/up2");
    assert_entry_is_none(&tree, "dir/up2-self");
    assert_entry_is_none(&tree, "selfdir/dir/up2");
    assert_entry_is_none(&tree, "selfdir/dir/up2/file.txt");
    assert_entry_is_none(&tree, "selfdir/dir/up2-self/file.txt");
    assert_entry_is_none(&tree, "selfdir/dir/up2/selfdir/up1/file.txt");
}

#[test]
fn entry_traverse_through_file() {
    let tree = make_tree(vec![
        TypedPath::Link {
            path: Path::new("self"),
            target: Path::new("."),
        },
        TypedPath::Link {
            path: Path::new("dir/up"),
            target: Path::new(".."),
        },
        TypedPath::File {
            path: Path::new("file"),
            is_executable: false,
        },
        TypedPath::Link {
            path: Path::new("filelink"),
            target: Path::new("file"),
        },
        TypedPath::Link {
            path: Path::new("badlink"),
            target: Path::new("file/anything"),
        },
        TypedPath::Link {
            path: Path::new("dir/badlink1"),
            target: Path::new("../badlink"),
        },
        TypedPath::Link {
            path: Path::new("dir/badlink2"),
            target: Path::new("../file/anything"),
        },
    ]);
    assert_entry_is_err(&tree, "file/anything");
    assert_entry_is_err(&tree, "filelink/anything");
    assert_entry_is_err(&tree, "self/file/anything");
    assert_entry_is_err(&tree, "self/filelink/anything");
    assert_entry_is_err(&tree, "dir/up/file/anything");
    assert_entry_is_err(&tree, "dir/up/filelink/anything");
    assert_entry_is_err(&tree, "badlink");
    assert_entry_is_err(&tree, "dir/badlink1");
    assert_entry_is_err(&tree, "dir/badlink2");
}

#[test]
fn entry_infinite_loop() {
    let tree = make_tree(vec![
        TypedPath::Link {
            path: Path::new("self"),
            target: Path::new("self"),
        },
        TypedPath::Link {
            path: Path::new("also-self"),
            target: Path::new("./self"),
        },
        TypedPath::Link {
            path: Path::new("subdir/self-through-parent"),
            target: Path::new("../self-through-parent"),
        },
        TypedPath::Link {
            path: Path::new("chain1"),
            target: Path::new("chain2"),
        },
        TypedPath::Link {
            path: Path::new("chain2"),
            target: Path::new("chain3"),
        },
        TypedPath::Link {
            path: Path::new("chain3"),
            target: Path::new("chain1"),
        },
    ]);
    assert_entry_is_none(&tree, "self");
    assert_entry_is_none(&tree, "also-self");
    assert_entry_is_none(&tree, "chain1");
    assert_entry_is_none(&tree, "chain2");
    assert_entry_is_none(&tree, "chain3");
    assert_entry_is_none(&tree, "subdir/self-through-parent");
}

#[test]
fn entry_absolute() {
    let tree = make_tree(vec![TypedPath::Link {
        path: Path::new("absolute"),
        target: Path::new("/etc/gitconfig"),
    }]);
    assert_entry_is_none(&tree, "absolute");
}

#[test]
fn entry_dead_link() {
    let tree = make_tree(vec![TypedPath::Link {
        path: Path::new("dead"),
        target: Path::new("nonexistant"),
    }]);
    assert_entry_is_none(&tree, "dead");
}

#[test]
fn entry_gnarly_symlinks() {
    let tree = make_tree(vec![
        TypedPath::Link {
            path: Path::new("dir/parent"),
            target: Path::new(".."),
        },
        TypedPath::Link {
            path: Path::new("dir/self"),
            target: Path::new("."),
        },
        TypedPath::Link {
            path: Path::new("dir/self_obtusely"),
            target: Path::new("../dir"),
        },
        TypedPath::Link {
            path: Path::new("dir/self_but_oh_so_obtusely"),
            target: Path::new(
                "self/self/self/self/self_obtusely/parent/dir/parent/dir/parent/dir/self",
            ),
        },
        TypedPath::File {
            path: Path::new("dir/file.txt"),
            is_executable: false,
        },
    ]);
    assert_entry_is_some(&tree, "dir/self_but_oh_so_obtusely");
    assert_entry_is_some(&tree, "dir/self_but_oh_so_obtusely/file.txt");
}

fn assert_walk(tree: &DigestTrie, expected_filenames: Vec<String>, expected_dirnames: Vec<String>) {
    let mut filenames = Vec::new();
    let mut dirnames = Vec::new();
    tree.walk(
        crate::SymlinkBehavior::Oblivious,
        &mut |path, entry| match entry {
            Entry::Symlink(_) => panic!("But we're oblivious!"),
            Entry::Directory(_) => dirnames.push(path.to_path_buf()),
            Entry::File(_) => filenames.push(path.to_path_buf()),
        },
    );
    assert_eq!(
        filenames,
        expected_filenames
            .iter()
            .map(PathBuf::from)
            .collect::<Vec<_>>()
    );
    assert_eq!(
        dirnames,
        expected_dirnames
            .iter()
            .map(PathBuf::from)
            .collect::<Vec<_>>()
    );
}

#[test]
fn walk_simple() {
    let tree = make_tree(vec![
        TypedPath::File {
            path: Path::new("file.txt"),
            is_executable: false,
        },
        TypedPath::Link {
            path: Path::new("symlink"),
            target: Path::new("file.txt"),
        },
        TypedPath::Link {
            path: Path::new("relsymlink"),
            target: Path::new("./file.txt"),
        },
        TypedPath::Link {
            path: Path::new("a/symlink"),
            target: Path::new("../file.txt"),
        },
        TypedPath::Link {
            path: Path::new("a/b/symlink"),
            target: Path::new("../../file.txt"),
        },
    ]);
    assert_walk(
        &tree,
        vec![
            "a/b/symlink".to_string(),
            "a/symlink".to_string(),
            "file.txt".to_string(),
            "relsymlink".to_string(),
            "symlink".to_string(),
        ],
        vec!["".to_string(), "a".to_string(), "a/b".to_string()],
    );
}

#[test]
fn walk_too_many_links_rootdir() {
    let tree = make_tree(vec![
        TypedPath::File {
            path: Path::new("file.txt"),
            is_executable: false,
        },
        TypedPath::Link {
            path: Path::new("self"),
            target: Path::new("."),
        },
    ]);
    assert_walk(
        &tree,
        (0..MAX_LINK_DEPTH)
            .into_iter()
            .map(|n| ("self/".repeat(n.into()) + "file.txt"))
            .collect::<Vec<_>>(),
        vec!["".to_string()],
    );
}

#[test]
fn walk_too_many_links_subdir() {
    let tree = make_tree(vec![
        TypedPath::File {
            path: Path::new("a/file.txt"),
            is_executable: false,
        },
        TypedPath::Link {
            path: Path::new("a/self"),
            target: Path::new("."),
        },
    ]);
    assert_walk(
        &tree,
        (0..MAX_LINK_DEPTH)
            .into_iter()
            .map(|n| ("a/".to_string() + &"self/".repeat(n.into()) + "file.txt"))
            .collect::<Vec<_>>(),
        vec!["".to_string(), "a".to_string()],
    );
}
