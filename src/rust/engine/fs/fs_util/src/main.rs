extern crate bazel_protos;
extern crate clap;
extern crate fs;

use clap::{App, Arg, SubCommand};
use fs::hash::Fingerprint;
use fs::store::Store;
use std::error::Error;
use std::fs::File;
use std::io::{self, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::exit;

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
Outputs a fingerprint of its contents.",
              )
              .arg(Arg::with_name("path").required(true).takes_value(true)),
          ),
      )
      .subcommand(
        SubCommand::with_name("directory").subcommand(
          SubCommand::with_name("save")
            .about(
              "Ingest a directory recursively. Saves all files found therein and saves Directory \
protos for each directory found. Outputs a fingerprint of the canonical top-level Directory proto.",
            )
            .arg(Arg::with_name("source").required(true).takes_value(true)),
        ),
      )
      .arg(
        Arg::with_name("local_store_path")
          .takes_value(true)
          .required(true),
      )
      .get_matches(),
  ) {
    Ok(_) => {}
    Err(err) => {
      eprintln!("{}", err);
      exit(1)
    }
  };
}

fn execute(top_match: clap::ArgMatches) -> Result<(), String> {
  let store_dir = top_match.value_of("store_dir").unwrap();
  let store = Store::new(store_dir).map_err(|e| {
    format!(
      "Failed to open/create store for directory {}: {}",
      store_dir,
      e
    )
  })?;

  match top_match.subcommand() {
    ("file", Some(sub_match)) => {
      match sub_match.subcommand() {
        ("cat", Some(args)) => {
          let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
          match store.load_bytes(&fingerprint)? {
            Some(bytes) => {
              io::stdout().write(&bytes).unwrap();
              Ok(())
            }
            None => Err(format!("File with fingerprint {} not found", fingerprint)),
          }
        }
        ("save", Some(args)) => {
          save_file(&store, &PathBuf::from(args.value_of("path").unwrap()))
            .map(|(fingerprint, _)| println!("{}", fingerprint))
        }
        (_, _) => unimplemented!(),
      }
    }
    ("directory", Some(sub_match)) => {
      match sub_match.subcommand() {
        ("save", Some(args)) => {
          save_directory(&store, &PathBuf::from(args.value_of("source").unwrap()))
            .map(|(fingerprint, _)| println!("{}", fingerprint))
        }
        (_, _) => unimplemented!(),
      }
    }
    (_, _) => unimplemented!(),
  }
}

fn save_file(store: &Store, path: &Path) -> Result<(Fingerprint, usize), String> {
  let mut buf = Vec::new();
  File::open(path)
    .and_then(|mut f| f.read_to_end(&mut buf))
    .map_err(|e| {
      format!("Error reading file {:?}: {}", path, e.description())
    })?;
  Ok((store.store_file_bytes(&buf)?, buf.len()))
}

fn save_directory(store: &Store, root: &Path) -> Result<(Fingerprint, usize), String> {
  let mut directory = bazel_protos::remote_execution::Directory::new();
  for entry in fs::PosixFS::scandir_sync(fs::Dir(root.to_path_buf()), &root)
    .map_err(|e| {
      format!("Error listing directory {:?}: {}", root, e.description())
    })?
  {
    match entry {
      fs::Stat::Dir(fs::Dir(path)) => {
        let (fingerprint, proto_size_bytes) = save_directory(store, &path)?;
        directory.mut_directories().push({
          let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
          dir_node.set_name(file_name_as_utf8(&path)?);
          dir_node.set_digest(fingerprint_to_digest(&fingerprint, proto_size_bytes as i64));
          dir_node
        })
      }
      fs::Stat::File(fs::File(path)) => {
        let (fingerprint, size_bytes) = save_file(store, &path)?;
        directory.mut_files().push({
          let mut file_node = bazel_protos::remote_execution::FileNode::new();
          file_node.set_name(file_name_as_utf8(&path)?);
          file_node.set_digest(fingerprint_to_digest(&fingerprint, size_bytes as i64));
          let mut absolute_path = root.to_path_buf();
          absolute_path.push(path.file_name().ok_or_else(|| {
            format!("{:?} did not have a file_name", path)
          })?);
          file_node.set_is_executable(
            std::fs::metadata(&absolute_path)
              .map_err(|e| e.description().to_string())?
              .permissions()
              .mode() & 1 == 1,
          );
          file_node
        });
      }
      fs::Stat::Link(fs::Link(path)) => {
        return Err(format!("Don't yet know how to handle symlinks: {:?}", path))
      }
    }
  }
  store.record_directory(&directory)
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
