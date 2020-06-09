use crate::{PlatformConstraint, Process, RelativePath};
use std::collections::hash_map::DefaultHasher;
use std::collections::{BTreeMap, BTreeSet};
use std::hash::{Hash, Hasher};
use std::time::Duration;

#[test]
fn process_equality() {
  // TODO: Tests like these would be cleaner with the builder pattern for the rust-side Process API.

  let process_generator = |description: String, timeout: Option<Duration>| Process {
    argv: vec![],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: hashing::EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout,
    description,
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  };

  fn hash<Hashable: Hash>(hashable: &Hashable) -> u64 {
    let mut hasher = DefaultHasher::new();
    hashable.hash(&mut hasher);
    hasher.finish()
  }

  let a = process_generator("One thing".to_string(), Some(Duration::new(0, 0)));
  let b = process_generator("Another".to_string(), Some(Duration::new(0, 0)));
  let c = process_generator("One thing".to_string(), Some(Duration::new(5, 0)));
  let d = process_generator("One thing".to_string(), None);

  // Process should derive a PartialEq and Hash that ignores the description
  assert!(a == b);
  assert!(hash(&a) == hash(&b));

  // ..but not other fields.
  assert!(a != c);
  assert!(hash(&a) != hash(&c));

  // Absence of timeout is included in hash.
  assert!(a != d);
  assert!(hash(&a) != hash(&d));
}

#[test]
fn relative_path_ok() {
  assert_eq!(Some("a"), RelativePath::new("a").unwrap().to_str());
  assert_eq!(Some("a"), RelativePath::new("./a").unwrap().to_str());
  assert_eq!(Some("a"), RelativePath::new("b/../a").unwrap().to_str());
  assert_eq!(
    Some("a/c"),
    RelativePath::new("b/../a/././c").unwrap().to_str()
  );
}

#[test]
fn relative_path_err() {
  assert!(RelativePath::new("../a").is_err());
  assert!(RelativePath::new("/a").is_err());
}
