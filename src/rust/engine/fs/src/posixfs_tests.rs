use tempfile;
use testutil;

use crate::{
  Dir, DirectoryListing, File, GitignoreStyleExcludes, GlobExpansionConjunction, GlobMatching,
  Link, PathGlobs, PathStat, PathStatGetter, PosixFS, Stat, StrictGlobMatching, SymlinkBehavior,
  VFS,
};

use async_trait::async_trait;
use std;
use std::collections::HashMap;
use std::path::{Components, Path, PathBuf};
use std::sync::Arc;
use testutil::make_file;

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
async fn read_file() {
  let dir = tempfile::TempDir::new().unwrap();
  let path = PathBuf::from("marmosets");
  let content = "cute".as_bytes().to_vec();
  make_file(
    &std::fs::canonicalize(dir.path()).unwrap().join(&path),
    &content,
    0o600,
  );
  let fs = new_posixfs(&dir.path());
  let file_content = fs
    .read_file(&File {
      path: path.clone(),
      is_executable: false,
    })
    .await
    .unwrap();
  assert_eq!(file_content.path, path);
  assert_eq!(file_content.content, content);
}

#[tokio::test]
async fn read_file_missing() {
  let dir = tempfile::TempDir::new().unwrap();
  new_posixfs(&dir.path())
    .read_file(&File {
      path: PathBuf::from("marmosets"),
      is_executable: false,
    })
    .await
    .expect_err("Expected error");
}

#[tokio::test]
async fn stat_executable_file() {
  let dir = tempfile::TempDir::new().unwrap();
  let posix_fs = new_posixfs(&dir.path());
  let path = PathBuf::from("photograph_marmosets");
  make_file(&dir.path().join(&path), &[], 0o700);
  assert_eq!(
    posix_fs.stat_sync(path.clone()).unwrap().unwrap(),
    super::Stat::File(File {
      path: path,
      is_executable: true,
    })
  )
}

#[tokio::test]
async fn stat_nonexecutable_file() {
  let dir = tempfile::TempDir::new().unwrap();
  let posix_fs = new_posixfs(&dir.path());
  let path = PathBuf::from("marmosets");
  make_file(&dir.path().join(&path), &[], 0o600);
  assert_eq!(
    posix_fs.stat_sync(path.clone()).unwrap().unwrap(),
    super::Stat::File(File {
      path: path,
      is_executable: false,
    })
  )
}

#[tokio::test]
async fn stat_dir() {
  let dir = tempfile::TempDir::new().unwrap();
  let posix_fs = new_posixfs(&dir.path());
  let path = PathBuf::from("enclosure");
  std::fs::create_dir(dir.path().join(&path)).unwrap();
  assert_eq!(
    posix_fs.stat_sync(path.clone()).unwrap().unwrap(),
    super::Stat::Dir(Dir(path))
  )
}

#[tokio::test]
async fn stat_symlink() {
  let dir = tempfile::TempDir::new().unwrap();
  let posix_fs = new_posixfs(&dir.path());
  let path = PathBuf::from("marmosets");
  make_file(&dir.path().join(&path), &[], 0o600);

  let link_path = PathBuf::from("remarkably_similar_marmoset");
  std::os::unix::fs::symlink(&dir.path().join(path), dir.path().join(&link_path)).unwrap();
  assert_eq!(
    posix_fs.stat_sync(link_path.clone()).unwrap().unwrap(),
    super::Stat::Link(Link(link_path))
  )
}

#[tokio::test]
async fn stat_symlink_oblivious() {
  let dir = tempfile::TempDir::new().unwrap();
  let posix_fs = new_posixfs_symlink_oblivious(&dir.path());
  let path = PathBuf::from("marmosets");
  make_file(&dir.path().join(&path), &[], 0o600);

  let link_path = PathBuf::from("remarkably_similar_marmoset");
  std::os::unix::fs::symlink(&dir.path().join(path), dir.path().join(&link_path)).unwrap();
  // Symlink oblivious stat will give us the destination type.
  assert_eq!(
    posix_fs.stat_sync(link_path.clone()).unwrap().unwrap(),
    super::Stat::File(File {
      path: link_path,
      is_executable: false,
    })
  )
}

#[tokio::test]
async fn stat_other() {
  new_posixfs("/dev")
    .stat_sync(PathBuf::from("null"))
    .expect_err("Want error");
}

#[tokio::test]
async fn stat_missing() {
  let dir = tempfile::TempDir::new().unwrap();
  let posix_fs = new_posixfs(&dir.path());
  assert_eq!(
    posix_fs.stat_sync(PathBuf::from("no_marmosets")).unwrap(),
    None,
  );
}

#[tokio::test]
async fn scandir_empty() {
  let dir = tempfile::TempDir::new().unwrap();
  let posix_fs = new_posixfs(&dir.path());
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

  let a_marmoset = path.join("a_marmoset");
  let feed = path.join("feed");
  let hammock = path.join("hammock");
  let remarkably_similar_marmoset = path.join("remarkably_similar_marmoset");
  let sneaky_marmoset = path.join("sneaky_marmoset");

  make_file(&dir.path().join(&feed), &[], 0o700);
  make_file(&dir.path().join(&a_marmoset), &[], 0o600);
  make_file(&dir.path().join(&sneaky_marmoset), &[], 0o600);
  std::os::unix::fs::symlink(
    &dir.path().join(&a_marmoset),
    dir
      .path()
      .join(&dir.path().join(&remarkably_similar_marmoset)),
  )
  .unwrap();
  std::fs::create_dir(dir.path().join(&hammock)).unwrap();
  make_file(
    &dir.path().join(&hammock).join("napping_marmoset"),
    &[],
    0o600,
  );

  // Symlink aware.
  assert_eq!(
    new_posixfs(&dir.path())
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
      Stat::Link(Link(remarkably_similar_marmoset.clone())),
      Stat::File(File {
        path: sneaky_marmoset.clone(),
        is_executable: false,
      }),
    ])
  );

  // Symlink oblivious.
  assert_eq!(
    new_posixfs_symlink_oblivious(&dir.path())
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
  let posix_fs = new_posixfs(&dir.path());
  posix_fs
    .scandir(Dir(PathBuf::from("no_marmosets_here")))
    .await
    .expect_err("Want error");
}

#[tokio::test]
async fn path_stats_for_paths() {
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
  std::fs::create_dir(&root_path.join("dir")).unwrap();
  std::os::unix::fs::symlink("executable_file", &root_path.join("symlink")).unwrap();
  std::os::unix::fs::symlink(
    "../symlink",
    &root_path.join("dir").join("recursive_symlink"),
  )
  .unwrap();
  std::os::unix::fs::symlink("dir", &root_path.join("dir_symlink")).unwrap();
  std::os::unix::fs::symlink("doesnotexist", &root_path.join("symlink_to_nothing")).unwrap();

  let posix_fs = Arc::new(new_posixfs(&root_path));
  let path_stats = posix_fs
    .path_stats(vec![
      PathBuf::from("executable_file"),
      PathBuf::from("regular_file"),
      PathBuf::from("dir"),
      PathBuf::from("symlink"),
      PathBuf::from("dir").join("recursive_symlink"),
      PathBuf::from("dir_symlink"),
      PathBuf::from("symlink_to_nothing"),
      PathBuf::from("doesnotexist"),
    ])
    .await
    .unwrap();
  let v: Vec<Option<PathStat>> = vec![
    Some(PathStat::file(
      PathBuf::from("executable_file"),
      File {
        path: PathBuf::from("executable_file"),
        is_executable: true,
      },
    )),
    Some(PathStat::file(
      PathBuf::from("regular_file"),
      File {
        path: PathBuf::from("regular_file"),
        is_executable: false,
      },
    )),
    Some(PathStat::dir(
      PathBuf::from("dir"),
      Dir(PathBuf::from("dir")),
    )),
    Some(PathStat::file(
      PathBuf::from("symlink"),
      File {
        path: PathBuf::from("executable_file"),
        is_executable: true,
      },
    )),
    Some(PathStat::file(
      PathBuf::from("dir").join("recursive_symlink"),
      File {
        path: PathBuf::from("executable_file"),
        is_executable: true,
      },
    )),
    Some(PathStat::dir(
      PathBuf::from("dir_symlink"),
      Dir(PathBuf::from("dir")),
    )),
    None,
    None,
  ];
  assert_eq!(v, path_stats);
}

#[tokio::test]
async fn memfs_expand_basic() {
  // Create two files, with the effect that there is a nested directory for the longer path.
  let p1 = PathBuf::from("some/file");
  let p2 = PathBuf::from("some/other");
  let fs = Arc::new(MemFS::new(vec![p1.clone(), p2.join("file")]));
  let globs = PathGlobs::new(
    vec!["some/*".into()],
    StrictGlobMatching::Ignore,
    GlobExpansionConjunction::AnyMatch,
  )
  .parse()
  .unwrap();

  assert_eq!(
    fs.expand_globs(globs).await.unwrap(),
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
    other => panic!("Expected file, got {:?}", other),
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

async fn read_mock_files(input: Vec<PathBuf>, posix_fs: &Arc<PosixFS>) -> Vec<Stat> {
  let path_stats = posix_fs.path_stats(input).await.unwrap();
  path_stats
    .into_iter()
    .map(|item| {
      let path_stat: PathStat = item.unwrap();
      match path_stat {
        PathStat::Dir { stat, .. } => Stat::Dir(stat),
        PathStat::File { stat, .. } => Stat::File(stat),
      }
    })
    .collect()
}

#[tokio::test]
async fn test_basic_gitignore_functionality() {
  let root = tempfile::TempDir::new().unwrap();
  let root_path = root.path();

  let bytes = "content".as_bytes();
  make_file(&root_path.join("non-ignored"), bytes, 0o700);
  make_file(&root_path.join("ignored-file.tmp"), bytes, 0o700);
  make_file(&root_path.join("important.x"), bytes, 0o700);
  make_file(&root_path.join("unimportant.x"), bytes, 0o700);

  let gitignore_content = "*.tmp\n!*.x";
  let gitignore_path = root_path.join(".gitignore");
  make_file(&gitignore_path, gitignore_content.as_bytes(), 0o700);
  let executor = task_executor::Executor::new();
  let ignorer =
    GitignoreStyleExcludes::create_with_gitignore_file(vec![], Some(gitignore_path.clone()))
      .unwrap();
  let posix_fs = Arc::new(PosixFS::new(root.as_ref(), ignorer, executor).unwrap());

  let stats = read_mock_files(
    vec![
      PathBuf::from("non-ignored"),
      PathBuf::from("ignored-file.tmp"),
      PathBuf::from("important.x"),
      PathBuf::from("unimportant.x"),
    ],
    &posix_fs,
  )
  .await;

  assert!(!posix_fs.is_ignored(&stats[0]));
  assert!(posix_fs.is_ignored(&stats[1]));
  assert!(!posix_fs.is_ignored(&stats[2]));
  assert!(!posix_fs.is_ignored(&stats[3]));

  // Test that .gitignore files work in tandem with explicit ignores.
  let executor = task_executor::Executor::new();
  let ignorer = GitignoreStyleExcludes::create_with_gitignore_file(
    vec!["unimportant.x".to_string()],
    Some(gitignore_path),
  )
  .unwrap();
  let posix_fs_2 = Arc::new(PosixFS::new(root.as_ref(), ignorer, executor).unwrap());

  assert!(!posix_fs_2.is_ignored(&stats[0]));
  assert!(posix_fs_2.is_ignored(&stats[1]));
  assert!(!posix_fs_2.is_ignored(&stats[2]));
  assert!(posix_fs_2.is_ignored(&stats[3]));
}

///
/// An in-memory implementation of VFS, useful for precisely reproducing glob matching behavior for
/// a set of file paths.
///
pub struct MemFS {
  contents: HashMap<Dir, Arc<DirectoryListing>>,
}

impl MemFS {
  pub fn new(paths: Vec<PathBuf>) -> MemFS {
    let mut unordered_contents = HashMap::new();
    let empty_path = PathBuf::new();
    for path in paths {
      Self::add_path(&mut unordered_contents, &empty_path, path.components());
    }
    let contents = unordered_contents
      .into_iter()
      .map(|(dir, mut stats)| {
        stats.sort_by(|a, b| a.path().cmp(b.path()));
        (dir, Arc::new(DirectoryListing(stats)))
      })
      .collect();
    MemFS { contents }
  }

  fn add_path(
    contents: &mut HashMap<Dir, Vec<Stat>>,
    path_so_far: &Path,
    mut remainder: Components,
  ) -> bool {
    if let Some(component) = remainder.next() {
      // The component represents a directory if it has child components: otherwise, a file.
      let path = path_so_far.join(component);
      let stat = if Self::add_path(contents, &path, remainder) {
        Stat::dir(path)
      } else {
        Stat::file(path, false)
      };
      contents
        .entry(Dir(path_so_far.to_owned()))
        .or_insert_with(Vec::new)
        .push(stat);
      true
    } else {
      false
    }
  }
}

#[async_trait]
impl VFS<String> for Arc<MemFS> {
  async fn read_link(&self, link: &Link) -> Result<PathBuf, String> {
    // The creation of a static filesystem does not allow for Links.
    Err(format!("{:?} does not exist within this filesystem.", link))
  }

  async fn scandir(&self, dir: Dir) -> Result<Arc<DirectoryListing>, String> {
    self
      .contents
      .get(&dir)
      .cloned()
      .ok_or_else(|| format!("{:?} does not exist within this filesystem.", dir))
  }

  fn is_ignored(&self, _stat: &Stat) -> bool {
    false
  }

  fn mk_error(msg: &str) -> String {
    msg.to_owned()
  }
}
