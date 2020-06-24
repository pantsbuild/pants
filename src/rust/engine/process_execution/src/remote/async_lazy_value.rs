#![allow(dead_code)]

use std::pin::Pin;
use std::sync::Arc;

use futures::Future;
use tokio::sync::Mutex;

struct Inner<T> {
  value: Option<T>,
  future: Option<Pin<Box<dyn Future<Output = T> + Send + 'static>>>,
}

pub struct AsyncLazyValue<T> {
  inner: Arc<Mutex<Inner<T>>>,
}

impl<T> AsyncLazyValue<T>
where
  T: Send + Clone + 'static,
{
  pub fn new<F>(future: F) -> Self
  where
    F: Future<Output = T> + Send + 'static,
  {
    let inner = Inner {
      value: None,
      future: Some(Box::pin(future)),
    };
    Self {
      inner: Arc::new(Mutex::new(inner)),
    }
  }

  pub async fn get(&self) -> T {
    let mut guard = self.inner.lock().await;

    if let Some(v) = &guard.value {
      return v.clone();
    }

    let fut = guard.future.take().expect("future must still be present");
    let v = fut.await;
    let result = v.clone();
    guard.value = Some(v);
    result
  }
}

impl<T> Clone for AsyncLazyValue<T> {
  fn clone(&self) -> Self {
    Self {
      inner: self.inner.clone(),
    }
  }
}

#[cfg(test)]
mod test {
  use super::AsyncLazyValue;
  use futures::future;

  #[tokio::test]
  async fn basic_test() {
    let fut = future::lazy(|_| "Hello world!".to_owned());

    let cached_value = AsyncLazyValue::new(fut);

    let v1 = cached_value.get().await;
    assert_eq!(v1, "Hello world!");

    let v2 = cached_value.get().await;
    assert_eq!(v2, "Hello world!");
  }

  #[tokio::test]
  async fn multiple_tasks_test() {
    let fut = future::lazy(|_| "Hello world!".to_owned());

    let cached_value = AsyncLazyValue::new(fut);
    let cached_value_clone = cached_value.clone();

    let handle = tokio::spawn(async move { cached_value_clone.get().await });

    let v_fut = cached_value.get();

    let (v1, v2) = future::join(handle, v_fut).await;
    assert_eq!(v1.unwrap(), "Hello world!");
    assert_eq!(v2, "Hello world!");
  }
}
