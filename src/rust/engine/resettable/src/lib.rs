// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy, default_trait_access, expl_impl_clone_on_copy, if_not_else, needless_continue,
    single_match_else, unseparated_literal_suffix, used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Subjective style.
#![cfg_attr(feature = "cargo-clippy", allow(len_without_is_empty, redundant_field_names))]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(feature = "cargo-clippy", allow(new_without_default, new_without_default_derive))]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![cfg_attr(feature = "cargo-clippy", allow(mutex_atomic))]

use std::sync::{Arc, RwLock};

///
/// Resettable is a lazily computed value which can be reset, so that it can be lazily computed
/// again next time it is needed.
///
/// This is useful because we fork without execing a lot in the engine, and before doing so, we need
/// to reset any references which hide background threads, so that forked processes don't inherit
/// pointers to threads from the parent process which will not exist in the forked process.
///
#[derive(Clone)]
pub struct Resettable<T> {
  val: Arc<RwLock<Option<T>>>,
  make: Arc<Fn() -> T>,
}

unsafe impl<T> Send for Resettable<T> {}
unsafe impl<T> Sync for Resettable<T> {}

impl<T> Resettable<T>
where
  T: Clone + Send + Sync,
{
  pub fn new<F: Fn() -> T + 'static>(make: F) -> Resettable<T> {
    Resettable {
      val: Arc::new(RwLock::new(None)),
      make: Arc::new(make),
    }
  }

  pub fn get(&self) -> T {
    {
      if let Some(ref val) = *self.val.read().unwrap() {
        return val.clone();
      }
    }
    {
      let mut maybe_val = self.val.write().unwrap();
      {
        if let Some(ref val) = *maybe_val {
          return val.clone();
        }
      }
      let val = (self.make)();
      *maybe_val = Some(val.clone());
      val
    }
  }

  pub fn reset(&self) {
    *self.val.write().unwrap() = None
  }
}
