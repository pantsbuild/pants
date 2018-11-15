extern crate flate2;
extern crate tar;
#[cfg(test)]
extern crate tempfile;
#[cfg(test)]
extern crate testutil;

use flate2::read::GzDecoder;
use std::fs::File;
use std::path::Path;
use tar::Archive;

pub fn decompress_tgz(tar_path: &Path, output_dir: &Path) -> Result<(), std::io::Error> {
  let tar_gz = File::open(tar_path)?;
  let tar = GzDecoder::new(tar_gz);
  let mut archive = Archive::new(tar);
  archive.unpack(output_dir)?;
  Ok(())
}

#[cfg(test)]
pub mod tar_tests {
  use super::decompress_tgz;
  use std::path::PathBuf;
  use tempfile;
  use testutil::make_file;
  use std::fs::File;
  use flate2::write::GzEncoder;
  use flate2::Compression;

//  #[test]
//  fn decompress_normal_tar_file() {
//    // prepare a file containing 'hello world'
//    let tmp_dir = tempfile::TempDir::new().unwrap();
//    let path = PathBuf::from("marmosets");
//    let content = "hello world".as_bytes().to_vec();
//    let full_path = std::fs::canonicalize(tmp_dir.path()).unwrap().join(&path);
//    make_file(
//      &full_path,
//      &content,
//      0o600,
//    );
//
//    // compress that file into a/b/c/hello.txt in the tar
//    let tar_gz_path = std::fs::canonicalize(tmp_dir.path()).unwrap().join(&"x.tgz");
//    let tar_gz_handle = File::create(tar_gz_path).unwrap();
//    let enc = GzEncoder::new(tar_gz_handle, Compression::default());
//    let mut tar = tar::Builder::new(enc);
//    tar.append_file("a/b/c/hello.txt", &mut File::open("test_data/hello.txt").unwrap());
//    tar.finish();
//
//    let tmp_dest_dir = tempfile::TempDir::new().unwrap();
//    let x = tar_gz_path.as_path().to_owned();
//    let result = decompress_tgz(&x, &tmp_dest_dir.path());
//    assert!(result.is_err())
//  }

  #[test]
  fn decompress_invalid_tar_file_path() {
    let result = decompress_tgz(&PathBuf::from("invalid_tar_path"), &PathBuf::from("a_dir"));
    assert!(result.is_err())
  }

  #[test]
  fn decompress_invalid_tar_content() {
    let dir = tempfile::TempDir::new().unwrap();
    let tar_filename = PathBuf::from("marmosets");
    let content = "definitely not a valid tar".as_bytes().to_vec();
    let tar_path = std::fs::canonicalize(dir.path()).unwrap().join(&tar_filename);
    make_file(
      &tar_path,
      &content,
      0o600,
    );
    let result = decompress_tgz(&tar_path, &PathBuf::from("a_dir"));
    assert!(result.is_err())
  }
}
