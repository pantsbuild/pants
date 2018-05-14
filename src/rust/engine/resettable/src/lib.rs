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
  // Sadly there is no way to accept an Fn() -> T because it's not Sized, so we need to accept an
  // Arc of one. This is not at all ergonomic, but at some point "impl trait" will come along and
  // allow us to remove this monstrosity.
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
