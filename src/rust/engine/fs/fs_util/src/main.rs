extern crate bazel_protos;
extern crate boxfuture;
extern crate clap;
extern crate fs;
extern crate futures;
extern crate protobuf;

use boxfuture::{Boxable, BoxFuture};
use clap::{App, Arg, SubCommand};
use fs::hash::Fingerprint;
use fs::store::Store;
use futures::future::{Future, join_all};
use std::error::Error;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::exit;
use std::sync::Arc;

#[derive(Debug)]
enum ExitCode {
  UnknownError = 1,
  NotFound = 2,
}

#[derive(Debug)]
struct ExitError(pub String, pub ExitCode);

impl From<String> for ExitError {
  fn from(s: String) -> Self {
    ExitError(s, ExitCode::UnknownError)
  }
}

fn main() {
  match execute(
    App::new("fs_util")
      .subcommand(
        SubCommand::with_name("file")
          .subcommand(
            SubCommand::with_name("cat")
              .about("Output the contents of a file by fingerprint.")
              .arg(Arg::with_name("fingerprint").required(true).takes_value(
                true,
              )),
          )
          .subcommand(
            SubCommand::with_name("save")
              .about(
                "Ingest a file by path, which allows it to be used in Directories/Snapshots. \
Outputs a fingerprint of its contents and its size in bytes, separated by a space.",
              )
              .arg(Arg::with_name("path").required(true).takes_value(true)),
          ),
      )
      .subcommand(
        SubCommand::with_name("directory")
          .subcommand(
            SubCommand::with_name("save")
              .about(
                "Ingest a directory recursively. Saves all files found therein and saves Directory \
protos for each directory found. Outputs a fingerprint of the canonical top-level Directory proto \
and the size of the serialized proto in bytes, separated by a space.",
              )
              .arg(Arg::with_name("source").required(true).takes_value(true)),
          )
          .subcommand(
            SubCommand::with_name("cat-proto")
              .about(
                "Output the bytes of a serialized Directory proto addressed by fingerprint.",
              )
              .arg(Arg::with_name("fingerprint").required(true).takes_value(
                true,
              )),
          ),
      )
      .arg(
        Arg::with_name("local_store_path")
          .takes_value(true)
          .long("local_store_path")
          .required(true),
      )
      .get_matches(),
  ) {
    Ok(_) => {}
    Err(err) => {
      eprintln!("{}", err.0);
      exit(err.1 as i32)
    }
  };
}

fn execute(top_match: clap::ArgMatches) -> Result<(), ExitError> {
  let store_dir = top_match.value_of("local_store_path").unwrap();
  let store = Arc::new(Store::new(store_dir).map_err(|e| {
    format!(
      "Failed to open/create store for directory {}: {}",
      store_dir,
      e
    )
  })?);

  match top_match.subcommand() {
    ("file", Some(sub_match)) => {
      match sub_match.subcommand() {
        ("cat", Some(args)) => {
          let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
          match store.load_file_bytes(&fingerprint)? {
            Some(bytes) => {
              io::stdout().write(&bytes).unwrap();
              Ok(())
            }
            None => Err(ExitError(
              format!("File with fingerprint {} not found", fingerprint),
              ExitCode::NotFound,
            )),
          }
        }
        ("save", Some(args)) => {
          let path = PathBuf::from(args.value_of("path").unwrap());
          // Canonicalize path to guarantee that a relative path has a parent.
          let posix_fs = make_posix_fs(path
            .canonicalize()
            .map_err(|e| {
              format!("Error canonicalizing path {:?}: {}", path, e.description())
            })?
            .parent()
            .ok_or_else(|| {
              format!("File being saved must have parent but {:?} did not", path)
            })?);
          let file = posix_fs
            .stat(PathBuf::from(path.file_name().unwrap()))
            .unwrap();
          match file {
            fs::Stat::File(f) => {
              let (fingerprint, size_bytes) = save_file(store, &posix_fs, f).wait().unwrap();
              Ok(println!("{} {}", fingerprint, size_bytes))
            }
            o => Err(ExitError(
              format!(
                "Tried to save file {:?} but it was not a file, was a {:?}",
                path,
                o
              ),
              ExitCode::UnknownError,
            )),
          }

        }
        (_, _) => unimplemented!(),
      }
    }
    ("directory", Some(sub_match)) => {
      match sub_match.subcommand() {
        ("save", Some(args)) => {
          let posix_fs = Arc::new(make_posix_fs(args.value_of("source").unwrap()));
          let (fingerprint, size_bytes) =
            save_directory(store, posix_fs, Arc::new(fs::Dir(PathBuf::from("."))))
              .wait()?;
          Ok(println!("{} {}", fingerprint, size_bytes))
        }
        ("cat-proto", Some(args)) => {
          let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
          match store.load_directory_proto_bytes(&fingerprint)? {
            Some(bytes) => {
              io::stdout().write(&bytes).unwrap();
              Ok(())
            }
            None => Err(ExitError(
              format!(
                "Directory with fingerprint {} not found",
                fingerprint
              ),
              ExitCode::NotFound,
            )),
          }
        }
        (_, _) => unimplemented!(),
      }
    }
    (_, _) => unimplemented!(),
  }
}

fn make_posix_fs<P: AsRef<Path>>(root: P) -> fs::PosixFS {
  fs::PosixFS::new(&root, vec![]).unwrap()
}

fn save_file(
  store: Arc<Store>,
  posix_fs: &fs::PosixFS,
  file: fs::File,
) -> BoxFuture<(Fingerprint, usize), String> {
  posix_fs
    .read_file(&file)
    .map_err(move |err| {
      format!("Error reading file {:?}: {}", file, err.description())
    })
    .and_then(move |content| {
      Ok((
        store.store_file_bytes(&content.content)?,
        content.content.len(),
      ))
    })
    .to_boxed()
}

fn save_directory(
  store: Arc<Store>,
  posix_fs: Arc<fs::PosixFS>,
  base_dir: Arc<fs::Dir>,
) -> BoxFuture<(Fingerprint, usize), String> {
  let store_copy = store.clone();
  Box::new(
    posix_fs
      .scandir(&base_dir)
      .map_err(move |err| {
        format!("Failed to scandir {:?}: {}", &base_dir, err.description())
      })
      .and_then(move |stats| {
        let mut dirs = Vec::new();
        let mut files = Vec::new();
        for stat in stats.into_iter() {
          match stat {
            fs::Stat::Dir(dir) => dirs.push(dir),
            fs::Stat::File(file) => files.push(file),
            fs::Stat::Link(fs::Link(path)) => {
              let err: BoxFuture<_, _> =
                futures::future::err(format!("Don't yet know how to handle symlinks: {:?}", path))
                  .to_boxed();
              return err;
            }
          }
        }

        let store_inner_copy = store_copy.clone();
        let posix_fs_copy = posix_fs.clone();
        let dir_futures: Vec<_> = dirs
          .into_iter()
          .map(move |dir| {
            let dir = Arc::new(dir);
            save_directory(store_inner_copy.clone(), posix_fs_copy.clone(), dir.clone())
              .and_then(move |(fingerprint, proto_size_bytes)| {
                let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
                dir_node.set_name(file_name_as_utf8(&dir.0)?);
                dir_node.set_digest(fingerprint_to_digest(&fingerprint, proto_size_bytes as i64));
                Ok(dir_node)
              })
          })
          .collect();

        let file_futures: Vec<_> = files
          .into_iter()
          .map(move |file| {
            file_to_file_node(store_copy.clone(), posix_fs.clone(), file)
          })
          .collect();

        join_all(dir_futures)
          .join(join_all(file_futures))
          .to_boxed()
      })
      .and_then(move |(dirs, files)| {
        let mut directory = bazel_protos::remote_execution::Directory::new();
        directory.set_directories(protobuf::RepeatedField::from_vec(dirs));
        directory.set_files(protobuf::RepeatedField::from_vec(files));
        store.record_directory(&directory)
      }),
  )
}

fn file_to_file_node(
  store: Arc<Store>,
  posix_fs: Arc<fs::PosixFS>,
  file: fs::File,
) -> BoxFuture<bazel_protos::remote_execution::FileNode, String> {
  let file_copy = file.clone();
  save_file(store, &posix_fs, file)
    .and_then(move |(fingerprint, size_bytes)| {
      let mut file_node = bazel_protos::remote_execution::FileNode::new();
      file_node.set_name(file_name_as_utf8(&file_copy.path)?);
      file_node.set_digest(fingerprint_to_digest(&fingerprint, size_bytes as i64));
      file_node.set_is_executable(file_copy.is_executable);
      Ok(file_node)
    })
    .to_boxed()
}

pub fn fingerprint_to_digest(
  fingerprint: &Fingerprint,
  size_bytes: i64,
) -> bazel_protos::remote_execution::Digest {
  let mut digest = bazel_protos::remote_execution::Digest::new();
  digest.set_hash(fingerprint.to_hex());
  digest.set_size_bytes(size_bytes);
  digest
}

fn file_name_as_utf8(path: &Path) -> Result<String, String> {
  match path.file_name() {
    Some(name) => {
      match name.to_str() {
        Some(name_utf8) => Ok(name_utf8.to_string()),
        None => Err(format!(
          "{:?}'s file_name is not representable in UTF8",
          path
        )),
      }
    }
    None => Err(format!("{:?} did not have a file_name", path)),
  }
}
