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
    let val = (make)();
    Resettable {
      val: Arc::new(RwLock::new(Some(val))),
      make: Arc::new(make),
    }
  }

  ///
  /// TODO: This probably needs to switch to a "with"/context-manager style pattern.
  /// Having an externalized `get` and using Clone like this is problematic: if there
  /// might be references/Clones of the field outside of the lock on the resource, then we can't
  /// be sure that dropping it will actually deallocate the resource.  
  ///
  pub fn get(&self) -> T {
    let val_opt = self.val.read().unwrap();
    let val = val_opt
      .as_ref()
      .unwrap_or_else(|| panic!("A Resettable value cannot be used while it is shutdown."));
    val.clone()
  }

  ///
  /// Run a function while the Resettable resource is cleared, and then recreate it afterward.
  ///
  pub fn with_reset<F, O>(&self, f: F) -> O
  where
    F: FnOnce() -> O,
  {
    let mut val = self.val.write().unwrap();
    *val = None;
    let t = f();
    *val = Some((self.make)());
    t
  }
}
