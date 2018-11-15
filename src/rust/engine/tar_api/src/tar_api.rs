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

  #[test]
  fn decompress_invalid_tar_file_path() {
    let result = decompress_tgz(&PathBuf::from("invalid_tar_path"), &PathBuf::from("a_dir"));
    assert!(result.is_err())
  }

  #[test]
  fn decompress_invalid_tar_content() {
    let dir = tempfile::TempDir::new().unwrap();
    let path = PathBuf::from("marmosets");
    let content = "definitely not a valid tar".as_bytes().to_vec();
    make_file(
      &std::fs::canonicalize(dir.path()).unwrap().join(&path),
      &content,
      0o600,
    );
    let result = decompress_tgz(&path, &PathBuf::from("a_dir"));
    assert!(result.is_err())
  }
}
