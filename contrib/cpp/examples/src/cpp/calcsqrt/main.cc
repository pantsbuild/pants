#include <cmath>
#include <limits>

double CalcSqrt(double d) {
  return sqrt(d);
}

int main() {
  double d = 100.0;
  double s = CalcSqrt(d);
  if (s < 10.0 - std::numeric_limits<double>::epsilon() ||
      s > 10.0 + std::numeric_limits<double>::epsilon()) {
    return 1;
  }
  return 0;
}
