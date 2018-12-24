// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy,
    default_trait_access,
    expl_impl_clone_on_copy,
    if_not_else,
    needless_continue,
    single_match_else,
    unseparated_literal_suffix,
    used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Subjective style.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(len_without_is_empty, redundant_field_names)
)]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(new_without_default, new_without_default_derive)
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![cfg_attr(feature = "cargo-clippy", allow(mutex_atomic))]

use bazel_protos;
use clap;
use dirs;

use errno;
use fs;
use fuse;

use futures_timer;

use libc;

use serverset;

use time;

use futures::future::Future;
use hashing::{Digest, Fingerprint};
use log::{debug, error, warn};
use parking_lot::Mutex;
use std::collections::hash_map::Entry::{Occupied, Vacant};
use std::collections::HashMap;
use std::ffi::{CString, OsStr, OsString};
use std::path::Path;
use std::sync::Arc;

const TTL: time::Timespec = time::Timespec { sec: 0, nsec: 0 };

const CREATE_TIME: time::Timespec = time::Timespec { sec: 1, nsec: 0 };

fn dir_attr_for(inode: Inode) -> fuse::FileAttr {
  attr_for(inode, 0, fuse::FileType::Directory, 0x555)
}

fn attr_for(inode: Inode, size: u64, kind: fuse::FileType, perm: u16) -> fuse::FileAttr {
  fuse::FileAttr {
    ino: inode,
    size: size,
    // TODO: Find out whether blocks is actaully important
    blocks: 0,
    atime: CREATE_TIME,
    mtime: CREATE_TIME,
    ctime: CREATE_TIME,
    crtime: CREATE_TIME,
    kind: kind,
    perm: perm,
    nlink: 1,
    uid: 0,
    gid: 0,
    rdev: 0,
    flags: 0,
  }
}

pub fn digest_from_filepath(str: &str) -> Result<Digest, String> {
  let mut parts = str.split('-');
  let fingerprint_str = parts
    .next()
    .ok_or_else(|| format!("Invalid digest: {} wasn't of form fingerprint-size", str))?;
  let fingerprint = Fingerprint::from_hex_string(fingerprint_str)?;
  let size_bytes = parts
    .next()
    .ok_or_else(|| format!("Invalid digest: {} wasn't of form fingerprint-size", str))?
    .parse::<usize>()
    .map_err(|err| format!("Invalid digest; size {} not a number: {}", str, err))?;
  Ok(Digest(fingerprint, size_bytes))
}

type Inode = u64;

const ROOT: Inode = 1;
const DIGEST_ROOT: Inode = 2;
const DIRECTORY_ROOT: Inode = 3;

#[derive(Clone, Copy, Debug)]
enum EntryType {
  File,
  Directory,
}

#[derive(Clone, Copy, Debug)]
struct InodeDetails {
  digest: Digest,
  entry_type: EntryType,
  is_executable: bool,
}

#[derive(Debug)]
struct ReaddirEntry {
  inode: Inode,
  kind: fuse::FileType,
  name: OsString,
}

enum Node {
  Directory(bazel_protos::remote_execution::DirectoryNode),
  File(bazel_protos::remote_execution::FileNode),
}

struct BuildResultFS {
  store: fs::Store,
  inode_digest_cache: HashMap<Inode, InodeDetails>,
  digest_inode_cache: HashMap<Digest, (Inode, Inode)>,
  directory_inode_cache: HashMap<Digest, Inode>,
  next_inode: Inode,
}

impl BuildResultFS {
  pub fn new(store: fs::Store) -> BuildResultFS {
    BuildResultFS {
      store: store,
      inode_digest_cache: HashMap::new(),
      digest_inode_cache: HashMap::new(),
      directory_inode_cache: HashMap::new(),
      next_inode: 4,
    }
  }
}

impl BuildResultFS {
  pub fn node_for_digest(
    &mut self,
    directory: &bazel_protos::remote_execution::Directory,
    filename: &str,
  ) -> Option<Node> {
    for file in directory.get_files() {
      if file.get_name() == filename {
        return Some(Node::File(file.clone()));
      }
    }
    for child in directory.get_directories() {
      if child.get_name() == filename {
        return Some(Node::Directory(child.clone()));
      }
    }
    None
  }

  pub fn inode_for_file(
    &mut self,
    digest: Digest,
    is_executable: bool,
  ) -> Result<Option<Inode>, String> {
    match self.digest_inode_cache.entry(digest) {
      Occupied(entry) => {
        let (executable_inode, non_executable_inode) = *entry.get();
        Ok(Some(if is_executable {
          executable_inode
        } else {
          non_executable_inode
        }))
      }
      Vacant(entry) => match self.store.load_file_bytes_with(digest, |_| ()).wait() {
        Ok(Some(())) => {
          let executable_inode = self.next_inode;
          self.next_inode += 1;
          let non_executable_inode = self.next_inode;
          self.next_inode += 1;
          entry.insert((executable_inode, non_executable_inode));
          self.inode_digest_cache.insert(
            executable_inode,
            InodeDetails {
              digest: digest,
              entry_type: EntryType::File,
              is_executable: true,
            },
          );
          self.inode_digest_cache.insert(
            non_executable_inode,
            InodeDetails {
              digest: digest,
              entry_type: EntryType::File,
              is_executable: false,
            },
          );
          Ok(Some(if is_executable {
            executable_inode
          } else {
            non_executable_inode
          }))
        }
        Ok(None) => Ok(None),
        Err(err) => Err(err),
      },
    }
  }

  pub fn inode_for_directory(&mut self, digest: Digest) -> Result<Option<Inode>, String> {
    match self.directory_inode_cache.entry(digest) {
      Occupied(entry) => Ok(Some(*entry.get())),
      Vacant(entry) => match self.store.load_directory(digest).wait() {
        Ok(Some(_)) => {
          // TODO: Kick off some background futures to pre-load the contents of this Directory into
          // an in-memory cache. Keep a background CPU pool driving those Futures.
          let inode = self.next_inode;
          self.next_inode += 1;
          entry.insert(inode);
          self.inode_digest_cache.insert(
            inode,
            InodeDetails {
              digest: digest,
              entry_type: EntryType::Directory,
              is_executable: true,
            },
          );
          Ok(Some(inode))
        }
        Ok(None) => Ok(None),
        Err(err) => Err(err),
      },
    }
  }

  pub fn file_attr_for(&mut self, inode: Inode) -> Option<fuse::FileAttr> {
    self.inode_digest_cache.get(&inode).map(|f| {
      attr_for(
        inode,
        f.digest.1 as u64,
        fuse::FileType::RegularFile,
        if f.is_executable { 0o555 } else { 0o444 },
      )
    })
  }

  pub fn dir_attr_for(&mut self, digest: Digest) -> Result<fuse::FileAttr, i32> {
    match self.inode_for_directory(digest) {
      Ok(Some(inode)) => Ok(dir_attr_for(inode)),
      Ok(None) => Err(libc::ENOENT),
      Err(err) => {
        error!("Error getting directory for digest {:?}: {}", digest, err);
        Err(libc::EINVAL)
      }
    }
  }

  pub fn readdir_entries(&mut self, inode: Inode) -> Result<Vec<ReaddirEntry>, i32> {
    match inode {
      ROOT => Ok(vec![
        ReaddirEntry {
          inode: ROOT,
          kind: fuse::FileType::Directory,
          name: OsString::from("."),
        },
        ReaddirEntry {
          inode: ROOT,
          kind: fuse::FileType::Directory,
          name: OsString::from(".."),
        },
        ReaddirEntry {
          inode: DIGEST_ROOT,
          kind: fuse::FileType::Directory,
          name: OsString::from("digest"),
        },
        ReaddirEntry {
          inode: DIRECTORY_ROOT,
          kind: fuse::FileType::Directory,
          name: OsString::from("directory"),
        },
      ]),
      // readdir on /digest or /directory will return an empty set.
      // readdir on /directory/abc123... will properly list the contents of that Directory.
      //
      // We skip directory listing for the roots because they will just be very long lists of
      // digests. The only other behaviours we could reasonable use are:
      //  1. Enumerate the entire contents of the local Store (which will be large), ignoring the
      //     remote Store (so the directory listing will still be incomplete - stuff which can be
      //     getattr'd/open'd will still not be present in the directory listing).
      //  2. Store a cache of requests we've successfully served, and claim that the directory
      //     contains exactly those files/directories.
      // All three of these end up with the same problem that readdir doesn't show things which, if
      // you were to getattr/open would actually exist. So we choose the cheapest, and most
      // consistent one: readdir is always empty.
      DIGEST_ROOT | DIRECTORY_ROOT => Ok(vec![]),
      inode => match self.inode_digest_cache.get(&inode) {
        Some(&InodeDetails {
          digest,
          entry_type: EntryType::Directory,
          ..
        }) => {
          let maybe_directory = self.store.load_directory(digest).wait();

          match maybe_directory {
            Ok(Some(directory)) => {
              let mut entries = vec![
                ReaddirEntry {
                  inode: inode,
                  kind: fuse::FileType::Directory,
                  name: OsString::from("."),
                },
                ReaddirEntry {
                  inode: DIRECTORY_ROOT,
                  kind: fuse::FileType::Directory,
                  name: OsString::from(".."),
                },
              ];

              let directories = directory.get_directories().iter().map(|directory| {
                (
                  directory.get_digest(),
                  directory.get_name(),
                  fuse::FileType::Directory,
                  true,
                )
              });
              let files = directory.get_files().iter().map(|file| {
                (
                  file.get_digest(),
                  file.get_name(),
                  fuse::FileType::RegularFile,
                  file.get_is_executable(),
                )
              });

              for (digest, name, filetype, is_executable) in directories.chain(files) {
                let child_digest_result: Result<Digest, String> = digest.into();
                let child_digest = child_digest_result.map_err(|err| {
                  error!("Error parsing digest: {:?}", err);
                  libc::ENOENT
                })?;
                let maybe_child_inode = match filetype {
                  fuse::FileType::Directory => self.inode_for_directory(child_digest),
                  fuse::FileType::RegularFile => self.inode_for_file(child_digest, is_executable),
                  _ => unreachable!(),
                };
                match maybe_child_inode {
                  Ok(Some(child_inode)) => {
                    entries.push(ReaddirEntry {
                      inode: child_inode,
                      kind: filetype,
                      name: OsString::from(name),
                    });
                  }
                  Ok(None) => {
                    return Err(libc::ENOENT);
                  }
                  Err(err) => {
                    error!("Error reading child directory {:?}: {}", child_digest, err);
                    return Err(libc::EINVAL);
                  }
                }
              }

              Ok(entries)
            }
            Ok(None) => Err(libc::ENOENT),
            Err(err) => {
              error!("Error loading directory {:?}: {}", digest, err);
              Err(libc::EINVAL)
            }
          }
        }
        _ => Err(libc::ENOENT),
      },
    }
  }
}

// inodes:
//  1: /
//  2: /digest
//  3: /directory
//  ... created on demand and cached for the lifetime of the program.
impl fuse::Filesystem for BuildResultFS {
  // Used to answer stat calls
  fn lookup(
    &mut self,
    _req: &fuse::Request<'_>,
    parent: Inode,
    name: &OsStr,
    reply: fuse::ReplyEntry,
  ) {
    let r = match (parent, name.to_str()) {
      (ROOT, Some("digest")) => Ok(dir_attr_for(DIGEST_ROOT)),
      (ROOT, Some("directory")) => Ok(dir_attr_for(DIRECTORY_ROOT)),
      (DIGEST_ROOT, Some(digest_str)) => match digest_from_filepath(digest_str) {
        Ok(digest) => self
          .inode_for_file(digest, true)
          .map_err(|err| {
            error!("Error loading file by digest {}: {}", digest_str, err);
            libc::EINVAL
          })
          .and_then(|maybe_inode| {
            maybe_inode
              .and_then(|inode| self.file_attr_for(inode))
              .ok_or(libc::ENOENT)
          }),
        Err(err) => {
          warn!("Invalid digest for file in digest root: {}", err);
          Err(libc::ENOENT)
        }
      },
      (DIRECTORY_ROOT, Some(digest_str)) => match digest_from_filepath(digest_str) {
        Ok(digest) => self.dir_attr_for(digest),
        Err(err) => {
          warn!("Invalid digest for directroy in directory root: {}", err);
          Err(libc::ENOENT)
        }
      },
      (parent, Some(filename)) => {
        let maybe_cache_entry = self
          .inode_digest_cache
          .get(&parent)
          .cloned()
          .ok_or(libc::ENOENT);
        maybe_cache_entry
          .and_then(|cache_entry| {
            let parent_digest = cache_entry.digest;
            self
              .store
              .load_directory(parent_digest)
              .wait()
              .map_err(|err| {
                error!("Error reading directory {:?}: {}", parent_digest, err);
                libc::EINVAL
              })?
              .and_then(|directory| self.node_for_digest(&directory, filename))
              .ok_or(libc::ENOENT)
          })
          .and_then(|node| match node {
            Node::Directory(directory_node) => {
              let digest_result: Result<Digest, String> = directory_node.get_digest().into();
              let digest = digest_result.map_err(|err| {
                error!("Error parsing digest: {:?}", err);
                libc::ENOENT
              })?;
              self.dir_attr_for(digest)
            }
            Node::File(file_node) => {
              let digest_result: Result<Digest, String> = file_node.get_digest().into();
              let digest = digest_result.map_err(|err| {
                error!("Error parsing digest: {:?}", err);
                libc::ENOENT
              })?;
              self
                .inode_for_file(digest, file_node.get_is_executable())
                .map_err(|err| {
                  error!("Error loading file by digest {}: {}", filename, err);
                  libc::EINVAL
                })
                .and_then(|maybe_inode| {
                  maybe_inode
                    .and_then(|inode| self.file_attr_for(inode))
                    .ok_or(libc::ENOENT)
                })
            }
          })
      }
      _ => Err(libc::ENOENT),
    };
    match r {
      Ok(r) => reply.entry(&TTL, &r, 1),
      Err(err) => reply.error(err),
    }
  }

  fn getattr(&mut self, _req: &fuse::Request<'_>, inode: Inode, reply: fuse::ReplyAttr) {
    match inode {
      ROOT => reply.attr(&TTL, &dir_attr_for(ROOT)),
      DIGEST_ROOT => reply.attr(&TTL, &dir_attr_for(DIGEST_ROOT)),
      DIRECTORY_ROOT => reply.attr(&TTL, &dir_attr_for(DIRECTORY_ROOT)),
      _ => match self.inode_digest_cache.get(&inode) {
        Some(&InodeDetails {
          entry_type: EntryType::File,
          ..
        }) => match self.file_attr_for(inode) {
          Some(file_attr) => reply.attr(&TTL, &file_attr),
          None => reply.error(libc::ENOENT),
        },
        Some(&InodeDetails {
          entry_type: EntryType::Directory,
          ..
        }) => reply.attr(&TTL, &dir_attr_for(inode)),
        _ => reply.error(libc::ENOENT),
      },
    }
  }

  // TODO: Find out whether fh is ever passed if open isn't explicitly implemented (and whether offset is ever negative)
  fn read(
    &mut self,
    _req: &fuse::Request<'_>,
    inode: Inode,
    _fh: u64,
    offset: i64,
    size: u32,
    reply: fuse::ReplyData,
  ) {
    match self.inode_digest_cache.get(&inode) {
      Some(&InodeDetails {
        digest,
        entry_type: EntryType::File,
        ..
      }) => {
        let reply = Arc::new(Mutex::new(Some(reply)));
        let reply2 = reply.clone();
        // TODO: Read from a cache of Futures driven from a CPU pool, so we can merge in-flight
        // requests, rather than reading from the store directly here.
        let result: Result<(), ()> = self
          .store
          .load_file_bytes_with(digest, move |bytes| {
            let begin = std::cmp::min(offset as usize, bytes.len());
            let end = std::cmp::min(offset as usize + size as usize, bytes.len());
            let mut reply = reply.lock();
            reply.take().unwrap().data(&bytes.slice(begin, end));
          })
          .map(|v| {
            if v.is_none() {
              let maybe_reply = reply2.lock().take();
              if let Some(reply) = maybe_reply {
                reply.error(libc::ENOENT);
              }
            }
          })
          .or_else(|err| {
            error!("Error loading bytes for {:?}: {}", digest, err);
            let maybe_reply = reply2.lock().take();
            if let Some(reply) = maybe_reply {
              reply.error(libc::EINVAL);
            }
            Ok(())
          })
          .wait();
        result.expect("Error from read future which should have been handled in the future ");
      }
      _ => reply.error(libc::ENOENT),
    }
  }

  fn readdir(
    &mut self,
    _req: &fuse::Request<'_>,
    inode: Inode,
    // TODO: Find out whether fh is ever passed if open isn't explicitly implemented (and whether offset is ever negative)
    _fh: u64,
    offset: i64,
    mut reply: fuse::ReplyDirectory,
  ) {
    match self.readdir_entries(inode) {
      Ok(entries) => {
        // 0 is a magic offset which means no offset, whereas a non-zero offset means start
        // _after_ that entry. Inconsistency is fun.
        let to_skip = if offset == 0 { 0 } else { offset + 1 } as usize;
        let mut i = offset;
        for entry in entries.into_iter().skip(to_skip) {
          if reply.add(entry.inode, i, entry.kind, entry.name) {
            // Buffer is full, don't add more entries.
            break;
          }
          i += 1;
        }
        reply.ok();
      }
      Err(err) => reply.error(err),
    }
  }

  // If this isn't implemented, OSX will try to manipulate ._ files to manage xattrs out of band, which adds both overhead and logspam.
  fn listxattr(
    &mut self,
    _req: &fuse::Request<'_>,
    _inode: Inode,
    _size: u32,
    reply: fuse::ReplyXattr,
  ) {
    reply.size(0);
  }
}

pub fn mount<'a, P: AsRef<Path>>(
  mount_path: P,
  store: fs::Store,
) -> std::io::Result<fuse::BackgroundSession<'a>> {
  // TODO: Work out how to disable caching in the filesystem
  let options = ["-o", "ro", "-o", "fsname=brfs", "-o", "noapplexattr"]
    .iter()
    .map(|o| o.as_ref())
    .collect::<Vec<&OsStr>>();

  debug!("About to spawn_mount with options {:?}", options);

  let fs = unsafe { fuse::spawn_mount(BuildResultFS::new(store), &mount_path, &options) };
  // fuse::spawn_mount doesn't always fully initialise the filesystem before returning.
  // Bluntly sleep for a bit here. If this poses a problem, we should maybe start doing some polling
  // stats or something until the filesystem seems to be correct.
  std::thread::sleep(std::time::Duration::from_secs(1));
  debug!("Did spawn mount");
  fs
}

fn main() {
  let default_store_path = dirs::home_dir()
    .expect("Couldn't find homedir")
    .join(".cache")
    .join("pants")
    .join("lmdb_store");

  let args = clap::App::new("brfs")
    .arg(
      clap::Arg::with_name("local-store-path")
        .takes_value(true)
        .long("local-store-path")
        .default_value_os(default_store_path.as_ref())
        .required(false),
    ).arg(
      clap::Arg::with_name("server-address")
        .takes_value(true)
        .long("server-address")
        .required(false),
    ).arg(
      clap::Arg::with_name("remote-instance-name")
        .takes_value(true)
        .long("remote-instance-name")
        .required(false),
    ).arg(
      clap::Arg::with_name("root-ca-cert-file")
          .help("Path to file containing root certificate authority certificates. If not set, TLS will not be used when connecting to the remote.")
          .takes_value(true)
          .long("root-ca-cert-file")
          .required(false)
    ).arg(clap::Arg::with_name("oauth-bearer-token-file")
        .help("Path to file containing oauth bearer token. If not set, no authorization will be provided to remote servers.")
        .takes_value(true)
        .long("oauth-bearer-token-file")
        .required(false)
  ).arg(
      clap::Arg::with_name("mount-path")
        .required(true)
        .takes_value(true),
    ).get_matches();

  let mount_path = args.value_of("mount-path").unwrap();
  let store_path = args.value_of("local-store-path").unwrap();

  // Unmount whatever happens to be mounted there already.
  // This is handy for development, but should probably be removed :)
  let unmount_return = unmount(mount_path);
  if unmount_return != 0 {
    match errno::errno() {
      errno::Errno(22) => {
        debug!("unmount failed, continuing because error code suggests directory was not mounted")
      }
      v => panic!("Error unmounting: {:?}", v),
    }
  }

  let root_ca_certs = if let Some(path) = args.value_of("root-ca-cert-file") {
    Some(std::fs::read(path).expect("Error reading root CA certs file"))
  } else {
    None
  };

  let oauth_bearer_token = if let Some(path) = args.value_of("oauth-bearer-token-file") {
    Some(std::fs::read_to_string(path).expect("Error reading oauth bearer token file"))
  } else {
    None
  };

  let pool = Arc::new(fs::ResettablePool::new("brfs-".to_owned()));
  let store = match args.value_of("server-address") {
    Some(address) => fs::Store::with_remote(
      &store_path,
      pool,
      &[address.to_owned()],
      args.value_of("remote-instance-name").map(str::to_owned),
      &root_ca_certs,
      oauth_bearer_token,
      1,
      4 * 1024 * 1024,
      std::time::Duration::from_secs(5 * 60),
      // TODO: Take a command line arg.
      serverset::BackoffConfig::new(
        std::time::Duration::from_secs(1),
        1.2,
        std::time::Duration::from_secs(20),
      )
      .expect("Error making BackoffConfig"),
      1,
      futures_timer::TimerHandle::default(),
    ),
    None => fs::Store::local_only(&store_path, pool),
  }
  .expect("Error making store");

  let _fs = mount(mount_path, store).expect("Error mounting");
  loop {
    std::thread::sleep(std::time::Duration::from_secs(1));
  }
}

#[cfg(target_os = "macos")]
fn unmount(mount_path: &str) -> i32 {
  unsafe {
    let path = CString::new(mount_path).unwrap();
    libc::unmount(path.as_ptr(), 0)
  }
}

#[cfg(target_os = "linux")]
fn unmount(mount_path: &str) -> i32 {
  unsafe {
    let path = CString::new(mount_path).unwrap();
    libc::umount(path.as_ptr())
  }
}

#[cfg(test)]
mod test {
  use tempfile;
  use testutil;

  use super::mount;
  use fs;
  use futures::future::Future;
  use hashing;
  use std::sync::Arc;
  use testutil::{
    data::{TestData, TestDirectory},
    file,
  };

  #[test]
  fn missing_digest() {
    let (store_dir, mount_dir) = make_dirs();

    let store = fs::Store::local_only(
      store_dir.path(),
      Arc::new(fs::ResettablePool::new("test-pool-".to_string())),
    )
    .expect("Error creating local store");

    let _fs = mount(mount_dir.path(), store).expect("Mounting");
    assert!(!&mount_dir
      .path()
      .join("digest")
      .join(digest_to_filepath(&TestData::roland().digest()))
      .exists());
  }

  #[test]
  fn read_file_by_digest() {
    let (store_dir, mount_dir) = make_dirs();

    let store = fs::Store::local_only(
      store_dir.path(),
      Arc::new(fs::ResettablePool::new("test-pool-".to_string())),
    )
    .expect("Error creating local store");

    let test_bytes = TestData::roland();

    store
      .store_file_bytes(test_bytes.bytes(), false)
      .wait()
      .expect("Storing bytes");

    let _fs = mount(mount_dir.path(), store).expect("Mounting");
    let file_path = mount_dir
      .path()
      .join("digest")
      .join(digest_to_filepath(&test_bytes.digest()));
    assert_eq!(test_bytes.bytes(), file::contents(&file_path));
    assert!(file::is_executable(&file_path));
  }

  #[test]
  fn list_directory() {
    let (store_dir, mount_dir) = make_dirs();

    let store = fs::Store::local_only(
      store_dir.path(),
      Arc::new(fs::ResettablePool::new("test-pool-".to_string())),
    )
    .expect("Error creating local store");

    let test_bytes = TestData::roland();
    let test_directory = TestDirectory::containing_roland();

    store
      .store_file_bytes(test_bytes.bytes(), false)
      .wait()
      .expect("Storing bytes");
    store
      .record_directory(&test_directory.directory(), false)
      .wait()
      .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store).expect("Mounting");
    let virtual_dir = mount_dir
      .path()
      .join("directory")
      .join(digest_to_filepath(&test_directory.digest()));
    assert_eq!(vec!["roland"], file::list_dir(&virtual_dir));
  }

  #[test]
  fn read_file_from_directory() {
    let (store_dir, mount_dir) = make_dirs();

    let store = fs::Store::local_only(
      store_dir.path(),
      Arc::new(fs::ResettablePool::new("test-pool-".to_string())),
    )
    .expect("Error creating local store");

    let test_bytes = TestData::roland();
    let test_directory = TestDirectory::containing_roland();

    store
      .store_file_bytes(test_bytes.bytes(), false)
      .wait()
      .expect("Storing bytes");
    store
      .record_directory(&test_directory.directory(), false)
      .wait()
      .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store).expect("Mounting");
    let roland = mount_dir
      .path()
      .join("directory")
      .join(digest_to_filepath(&test_directory.digest()))
      .join("roland");
    assert_eq!(test_bytes.bytes(), file::contents(&roland));
    assert!(!file::is_executable(&roland));
  }

  #[test]
  fn list_recursive_directory() {
    let (store_dir, mount_dir) = make_dirs();

    let store = fs::Store::local_only(
      store_dir.path(),
      Arc::new(fs::ResettablePool::new("test-pool-".to_string())),
    )
    .expect("Error creating local store");

    let test_bytes = TestData::roland();
    let treat_bytes = TestData::catnip();
    let test_directory = TestDirectory::containing_roland();
    let recursive_directory = TestDirectory::recursive();

    store
      .store_file_bytes(test_bytes.bytes(), false)
      .wait()
      .expect("Storing bytes");
    store
      .store_file_bytes(treat_bytes.bytes(), false)
      .wait()
      .expect("Storing bytes");
    store
      .record_directory(&test_directory.directory(), false)
      .wait()
      .expect("Storing directory");
    store
      .record_directory(&recursive_directory.directory(), false)
      .wait()
      .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store).expect("Mounting");
    let virtual_dir = mount_dir
      .path()
      .join("directory")
      .join(digest_to_filepath(&recursive_directory.digest()));
    assert_eq!(vec!["cats", "treats"], file::list_dir(&virtual_dir));
    assert_eq!(vec!["roland"], file::list_dir(&virtual_dir.join("cats")));
  }

  #[test]
  fn read_file_from_recursive_directory() {
    let (store_dir, mount_dir) = make_dirs();

    let store = fs::Store::local_only(
      store_dir.path(),
      Arc::new(fs::ResettablePool::new("test-pool-".to_string())),
    )
    .expect("Error creating local store");

    let test_bytes = TestData::roland();
    let treat_bytes = TestData::catnip();
    let test_directory = TestDirectory::containing_roland();
    let recursive_directory = TestDirectory::recursive();

    store
      .store_file_bytes(test_bytes.bytes(), false)
      .wait()
      .expect("Storing bytes");
    store
      .store_file_bytes(treat_bytes.bytes(), false)
      .wait()
      .expect("Storing bytes");
    store
      .record_directory(&test_directory.directory(), false)
      .wait()
      .expect("Storing directory");
    store
      .record_directory(&recursive_directory.directory(), false)
      .wait()
      .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store).expect("Mounting");
    let virtual_dir = mount_dir
      .path()
      .join("directory")
      .join(digest_to_filepath(&recursive_directory.digest()));
    let treats = virtual_dir.join("treats");
    assert_eq!(treat_bytes.bytes(), file::contents(&treats));
    assert!(!file::is_executable(&treats));

    let roland = virtual_dir.join("cats").join("roland");
    assert_eq!(test_bytes.bytes(), file::contents(&roland));
    assert!(!file::is_executable(&roland));
  }

  #[test]
  fn files_are_correctly_executable() {
    let (store_dir, mount_dir) = make_dirs();

    let store = fs::Store::local_only(
      store_dir.path(),
      Arc::new(fs::ResettablePool::new("test-pool-".to_string())),
    )
    .expect("Error creating local store");

    let treat_bytes = TestData::catnip();
    let directory = TestDirectory::with_mixed_executable_files();

    store
      .store_file_bytes(treat_bytes.bytes(), false)
      .wait()
      .expect("Storing bytes");
    store
      .record_directory(&directory.directory(), false)
      .wait()
      .expect("Storing directory");

    let _fs = mount(mount_dir.path(), store).expect("Mounting");
    let virtual_dir = mount_dir
      .path()
      .join("directory")
      .join(digest_to_filepath(&directory.digest()));
    assert_eq!(vec!["feed", "food"], file::list_dir(&virtual_dir));
    assert!(file::is_executable(&virtual_dir.join("feed")));
    assert!(!file::is_executable(&virtual_dir.join("food")));
  }

  pub fn digest_to_filepath(digest: &hashing::Digest) -> String {
    format!("{}-{}", digest.0, digest.1)
  }

  pub fn make_dirs() -> (tempfile::TempDir, tempfile::TempDir) {
    let store_dir = tempfile::Builder::new().prefix("store").tempdir().unwrap();
    let mount_dir = tempfile::Builder::new().prefix("mount").tempdir().unwrap();
    (store_dir, mount_dir)
  }
}

// TODO: Write a bunch more syscall-y tests to test that each syscall for each file/directory type
// acts as we expect.
#[cfg(test)]
mod syscall_tests {
  use super::mount;
  use super::test::digest_to_filepath;
  use crate::test::make_dirs;
  use fs;
  use futures::Future;
  use libc;
  use std::ffi::CString;
  use std::path::Path;
  use std::sync::Arc;
  use testutil::data::TestData;

  #[test]
  fn read_file_by_digest_exact_bytes() {
    let (store_dir, mount_dir) = make_dirs();

    let store = fs::Store::local_only(
      store_dir.path(),
      Arc::new(fs::ResettablePool::new("test-pool-".to_string())),
    )
    .expect("Error creating local store");

    let test_bytes = TestData::roland();

    store
      .store_file_bytes(test_bytes.bytes(), false)
      .wait()
      .expect("Storing bytes");

    let _fs = mount(mount_dir.path(), store).expect("Mounting");

    let path = mount_dir
      .path()
      .join("digest")
      .join(digest_to_filepath(&test_bytes.digest()));

    let mut buf = make_buffer(test_bytes.len());

    unsafe {
      let fd = libc::open(path_to_cstring(&path).as_ptr(), 0);
      assert!(fd > 0, "Bad fd {}", fd);
      let read_bytes = libc::read(fd, buf.as_mut_ptr() as *mut libc::c_void, buf.len());
      assert_eq!(test_bytes.len() as isize, read_bytes);
      assert_eq!(0, libc::close(fd));
    }

    assert_eq!(test_bytes.string(), String::from_utf8(buf).unwrap());
  }

  fn path_to_cstring(path: &Path) -> CString {
    CString::new(path.to_string_lossy().as_bytes().to_owned()).unwrap()
  }

  fn make_buffer(size: usize) -> Vec<u8> {
    let mut buf: Vec<u8> = Vec::new();
    buf.resize(size, 0);
    buf
  }
}
