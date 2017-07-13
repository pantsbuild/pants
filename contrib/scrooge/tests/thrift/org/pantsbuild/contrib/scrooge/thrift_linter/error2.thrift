namespace scala scala2
namespace java java2

struct Quacker {
  1: optional i32 sound,
}

// Struct marked persisted, depending on non-persisted struct: error.
struct Duck {
  1: optional Quacker quack,
}(persisted = "true")
