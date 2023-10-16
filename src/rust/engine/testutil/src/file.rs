use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

pub fn list_dir(path: &Path) -> Vec<String> {
    let mut v: Vec<_> = std::fs::read_dir(path)
        .unwrap_or_else(|err| panic!("Listing dir {:?}: {:?}", path, err))
        .map(|entry| {
            entry
                .expect("Error reading entry")
                .file_name()
                .to_string_lossy()
                .to_string()
        })
        .collect();
    v.sort();
    v
}

pub fn contents(path: &Path) -> bytes::Bytes {
    let mut contents = Vec::new();
    std::fs::File::open(path)
        .and_then(|mut f| f.read_to_end(&mut contents))
        .expect("Error reading file");
    bytes::Bytes::from(contents)
}

pub fn is_executable(path: &Path) -> bool {
    std::fs::metadata(path)
        .map(|meta| meta.permissions().mode() & 0o100 == 0o100)
        .unwrap_or(false)
}
