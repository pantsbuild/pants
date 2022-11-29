use crate::externs::interface;

use std::any::Any;

#[test]
fn test_panic_string() {
  let a: &str = "a str panic payload";
  assert_eq!(
    interface::generate_panic_string(&a as &(dyn Any + Send)),
    "panic at 'a str panic payload'"
  );

  let b: String = "a String panic payload".to_string();
  assert_eq!(
    interface::generate_panic_string(&b as &(dyn Any + Send)),
    "panic at 'a String panic payload'"
  );

  let c: u32 = 18;
  let output = interface::generate_panic_string(&c as &(dyn Any + Send));
  assert!(output.contains("Non-string panic payload at"));
}

#[test]
fn test_matches_gitignore_style_globs() {
  assert_eq!(
    interface::matches_gitignore_style_globs(
      vec!["*".to_string()],
      vec!["a.py".to_string(), "b.rs".to_string()]
    )
    .unwrap(),
    vec!["a.py", "b.rs"]
  );
  assert_eq!(
    interface::matches_gitignore_style_globs(
      vec!["*.py".to_string()],
      vec!["a.py".to_string(), "b.rs".to_string()]
    )
    .unwrap(),
    vec!["a.py"]
  );
  assert_eq!(
    interface::matches_gitignore_style_globs(
      vec!["*.*".to_string(), "!b.rs".to_string()],
      vec!["a.py".to_string(), "b.rs".to_string()]
    )
    .unwrap(),
    vec!["a.py"]
  );
}
