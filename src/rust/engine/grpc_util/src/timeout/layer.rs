use super::Timeout;
use std::time::Duration;
use tower_layer::Layer;

/// Applies a timeout to requests via the supplied inner service.
#[derive(Debug, Clone)]
pub struct TimeoutLayer {
  timeout: Duration,
}

impl TimeoutLayer {
    /// Create a timeout from a duration
    pub fn new(timeout: Option<Duration>) -> Self {
        let timeout = timeout.unwrap_or_else(|| Duration::from_secs(60 * 60));
        TimeoutLayer { timeout }
    }
}

impl<S> Layer<S> for TimeoutLayer {
  type Service = Timeout<S>;

  fn layer(&self, service: S) -> Self::Service {
    Timeout::new(service, self.timeout)
  }
}
