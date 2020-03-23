// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

object GreetingEverybody {
  def greeting_by_name(name: String): String = {
    "Hello %s! How are you?".format(name)
  }
  def greeting_everybody(everybody: Seq[String]): Seq[String] = {
    everybody.map(name => greeting_by_name(name))
  }
}
