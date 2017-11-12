extern crate bazel_protos;
extern crate boxfuture;
extern crate clap;
extern crate fs;
extern crate itertools;
extern crate futures;
extern crate protobuf;

use boxfuture::{Boxable, BoxFuture};
use clap::{App, Arg, SubCommand};
use fs::hash::Fingerprint;
use fs::store::Store;
use fs::VFS;
use futures::future::{Future, join_all};
use itertools::Itertools;
use std::error::Error;
use std::ffi::OsString;
use std::fs::File;
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
            SubCommand::with_name("materialize")
              .about(
                "Materialize a directory by fingerprint to the filesystem. \
Destination must not exist before this command is run.",
              )
              .arg(Arg::with_name("fingerprint").required(true).takes_value(
                true,
              ))
              .arg(Arg::with_name("destination").required(true).takes_value(
                true,
              )),
          )
          .subcommand(
            SubCommand::with_name("save")
              .about(
                "Ingest a directory recursively. Saves all files found therein and saves Directory \
protos for each directory found. Outputs a fingerprint of the canonical top-level Directory proto \
and the size of the serialized proto in bytes, separated by a space.",
              )
              .arg(
                Arg::with_name("globs")
                  .required(true)
                  .takes_value(true)
                  .multiple(true)
                  .help(
                    "globs matching the files and directories which should be included in the \
directory, relative to the root.",
                  ),
              )
                .arg(Arg::with_name("root").long("root").required(true).takes_value(true).help(
                  "Root under which the globs live. The Directory proto produced will be relative \
to this directory.",
                )),
          )
          .subcommand(
            SubCommand::with_name("cat-proto")
              .about(
                "Output the bytes of a serialized Directory proto addressed by fingerprint.",
              )
              .arg(
                Arg::with_name("output-format")
                  .long("output-format")
                  .takes_value(true)
                  .default_value("binary")
                  .possible_values(&["binary", "text"]),
              )
              .arg(Arg::with_name("fingerprint").required(true).takes_value(
                true,
              )),
          ),
      )
      .subcommand(
        SubCommand::with_name("cat")
          .about(
            "Output the contents of a file or Directory proto addressed by fingerprint.",
          )
          .arg(Arg::with_name("fingerprint").required(true).takes_value(
            true,
          )),
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
              let (fingerprint, size_bytes) =
                save_file(store, Arc::new(posix_fs), f).wait().unwrap();
              Ok(println!("{} {}", fingerprint, size_bytes))
            }
            o => Err(
              format!(
                "Tried to save file {:?} but it was not a file, was a {:?}",
                path,
                o
              ).into(),
            ),
          }

        }
        (_, _) => unimplemented!(),
      }
    }
    ("directory", Some(sub_match)) => {
      match sub_match.subcommand() {
        ("materialize", Some(args)) => {
          let destination = Path::new(args.value_of("destination").unwrap());
          let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
          Ok(materialize_directory(store, destination, &fingerprint)?)
        }
        ("save", Some(args)) => {
          let posix_fs = Arc::new(make_posix_fs(args.value_of("root").unwrap()));
          let (fingerprint, size_bytes) = posix_fs
            .expand(fs::PathGlobs::create(
              &args
                .values_of("globs")
                .unwrap()
                .map(|s| s.to_string())
                .collect::<Vec<String>>(),
              &[],
            )?)
            .map_err(|e| format!("Error expanding globs: {}", e.description()))
            .and_then(move |paths| save_directory(store, posix_fs, paths))
            .wait()?;
          Ok(println!("{} {}", fingerprint, size_bytes))
        }
        ("cat-proto", Some(args)) => {
          let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
          let proto_bytes = match args.value_of("output-format").unwrap() {
            "binary" => store.load_directory_proto_bytes(&fingerprint),
            "text" => {
              store.load_directory_proto(&fingerprint).map(|maybe_p| {
                maybe_p.map(|p| format!("{:?}\n", p).as_bytes().to_vec())
              })
            }
            format => Err(format!(
              "Unexpected value of --output-format arg: {}",
              format
            )),
          }?;
          match proto_bytes {
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
    ("cat", Some(args)) => {
      let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
      let v = match store.load_file_bytes(&fingerprint)? {
        None => store.load_directory_proto_bytes(&fingerprint)?,
        some => some,
      };
      match v {
        Some(bytes) => {
          io::stdout().write(&bytes).unwrap();
          Ok(())
        }
        None => Err(ExitError(
          format!("Fingerprint {} not found", fingerprint),
          ExitCode::NotFound,
        )),
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
  posix_fs: Arc<fs::PosixFS>,
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
  mut path_stats: Vec<fs::PathStat>,
) -> BoxFuture<(Fingerprint, usize), String> {
  let mut file_futures: Vec<BoxFuture<bazel_protos::remote_execution::FileNode, String>> =
    Vec::new();
  let mut dir_futures: Vec<BoxFuture<bazel_protos::remote_execution::DirectoryNode, String>> =
    Vec::new();

  path_stats.sort_by(|a, b| a.path().cmp(b.path()));

  for (first_component, group) in
    &path_stats.into_iter().group_by(|s| {
      s.path().components().next().unwrap().as_os_str().to_owned()
    })
  {
    let mut path_group: Vec<fs::PathStat> = group.collect();
    if path_group.len() == 1 && path_group.get(0).unwrap().path().components().count() == 1 {
      // Exactly one entry with exactly one component indicates either a file in this directory, or
      // an empty directory.
      // If the child is a non-empty directory, or a file therein, there must be multiple PathStats
      // with that prefix component, and we will handle that in the recursive save_directory call.

      match path_group.pop().unwrap() {
        fs::PathStat::File { ref stat, .. } => {
          let is_executable = stat.is_executable;
          file_futures.push(
            save_file(store.clone(), posix_fs.clone(), stat.clone())
              .and_then(move |(fingerprint, size_bytes)| {
                let mut file_node = bazel_protos::remote_execution::FileNode::new();
                file_node.set_name(osstring_as_utf8(first_component)?);
                file_node.set_digest(fingerprint_to_digest(&fingerprint, size_bytes as i64));
                file_node.set_is_executable(is_executable);
                Ok(file_node)
              })
              .to_boxed(),
          );
        }
        fs::PathStat::Dir { .. } => {
          // Because there are no children of this Dir, it must be empty.
          let (fingerprint, size_bytes) = store
            .record_directory(&bazel_protos::remote_execution::Directory::new())
            .unwrap();
          let mut directory_node = bazel_protos::remote_execution::DirectoryNode::new();
          directory_node.set_name(osstring_as_utf8(first_component).unwrap());
          directory_node.set_digest(fingerprint_to_digest(&fingerprint, size_bytes as i64));
          dir_futures.push(futures::future::ok(directory_node).to_boxed());
        }
      }
    } else {
      dir_futures.push(
        save_directory(
          store.clone(),
          posix_fs.clone(),
          paths_of_child_dir(path_group),
        ).and_then(move |(fingerprint, size_bytes)| {
          let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
          dir_node.set_name(osstring_as_utf8(first_component)?);
          dir_node.set_digest(fingerprint_to_digest(&fingerprint, size_bytes as i64));
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
      store.record_directory(&directory)
    })
    .to_boxed()
}

fn paths_of_child_dir(paths: Vec<fs::PathStat>) -> Vec<fs::PathStat> {
  paths
    .into_iter()
    .filter_map(|s| {
      if s.path().components().count() == 1 {
        return None;
      }
      Some(match s {
        fs::PathStat::File { path, stat } => {
          fs::PathStat::File {
            path: path.iter().skip(1).collect(),
            stat: stat,
          }
        }
        fs::PathStat::Dir { path, stat } => {
          fs::PathStat::Dir {
            path: path.iter().skip(1).collect(),
            stat: stat,
          }
        }
      })
    })
    .collect()
}

fn materialize_directory(
  store: Arc<Store>,
  destination: &Path,
  fingerprint: &Fingerprint,
) -> Result<(), ExitError> {
  let directory = store.load_directory_proto(&fingerprint)?.ok_or_else(|| {
    ExitError(
      format!("Directory with fingerprint {} not found", fingerprint),
      ExitCode::NotFound,
    )
  })?;
  make_clean_dir(&destination).map_err(|e| {
    format!(
      "Error making directory {:?}: {}",
      destination,
      e.description()
    )
  })?;
  for file_node in directory.get_files() {
    let fingerprint = &Fingerprint::from_hex_string(&file_node.get_digest().get_hash())?;
    match store.load_file_bytes(fingerprint)? {
      Some(bytes) => {
        let path = destination.join(file_node.get_name());
        File::create(&path)
          .and_then(|mut f| f.write_all(&bytes))
          .map_err(|e| {
            format!("Error writing file {:?}: {}", path, e.description())
          })?;
      }
      None => {
        return Err(ExitError(
          format!(
            "File with fingerprint {} not found",
            file_node.get_digest().get_hash()
          ),
          ExitCode::NotFound,
        ))
      }
    }
  }
  for directory_node in directory.get_directories() {
    materialize_directory(
      store.clone(),
      &destination.join(directory_node.get_name()),
      &Fingerprint::from_hex_string(directory_node.get_digest().get_hash())?,
    )?;
  }
  Ok(())
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

fn osstring_as_utf8(path: OsString) -> Result<String, String> {
  path.into_string().map_err(|p| {
    format!("{:?}'s file_name is not representable in UTF8", p)
  })
}

fn make_clean_dir(path: &Path) -> Result<(), io::Error> {
  let parent = path.parent().ok_or_else(|| {
    io::Error::new(io::ErrorKind::NotFound, format!("{:?} had no parent", path))
  })?;
  std::fs::create_dir_all(parent)?;
  std::fs::create_dir(path)
}
