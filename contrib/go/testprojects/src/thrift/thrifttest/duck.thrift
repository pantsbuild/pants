// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

namespace go duck

struct Duck {
  1: optional string quack,
}

service EchoServer {
   void ping()
   string echo(1: string input)
}