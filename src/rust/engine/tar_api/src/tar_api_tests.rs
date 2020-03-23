use crate::decompress_tgz;
use flate2::write::GzEncoder;
use flate2::Compression;
use std::fs::File;
use std::path::{Path, PathBuf};
use tempfile::TempDir;
use testutil::file::contents;
use testutil::make_file;

#[test]
fn decompress_normal_tar_file() {
  // prepare a file containing 'hello world'
  let tmp_dir = TempDir::new().unwrap();
  let content = "hello world".as_bytes().to_vec();
  let txt_full_path = std::fs::canonicalize(tmp_dir.path())
    .unwrap()
    .join(&"hello.txt");
  make_file(&txt_full_path, &content, 0o600);

  let path_in_tar = "a/b/c/d.txt";
  let tgz_path = std::fs::canonicalize(tmp_dir.path())
    .unwrap()
    .join(&"simple.tgz");

  compress(&txt_full_path, &path_in_tar, &tgz_path).expect("Error compressing.");

  // uncompress the tgz then make sure the content is good.
  let tmp_dest_dir = tempfile::TempDir::new().unwrap();
  decompress_tgz(&tgz_path.as_path(), &tmp_dest_dir.path()).expect("Error decompressing.");
  let expected_txt_path = std::fs::canonicalize(tmp_dest_dir.path())
    .unwrap()
    .join(&path_in_tar);
  assert!(expected_txt_path.exists());
  assert_eq!(content, contents(&expected_txt_path))
}

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
  let tar_path = std::fs::canonicalize(dir.path())
    .unwrap()
    .join(&tar_filename);
  make_file(&tar_path, &content, 0o600);
  let result = decompress_tgz(&tar_path, &PathBuf::from("a_dir"));
  assert!(result.is_err())
}

fn compress(
  txt_full_path: &Path,
  path_in_tar: &str,
  tar_full_path: &Path,
) -> Result<(), std::io::Error> {
  // compress that file into a/b/c/hello.txt in the tar
  let enc = GzEncoder::new(
    File::create(tar_full_path.clone()).unwrap(),
    Compression::default(),
  );
  let mut tar = tar::Builder::new(enc);
  tar.append_file(path_in_tar, &mut File::open(txt_full_path.clone()).unwrap())?;
  tar.into_inner()?;
  Ok(())
}
