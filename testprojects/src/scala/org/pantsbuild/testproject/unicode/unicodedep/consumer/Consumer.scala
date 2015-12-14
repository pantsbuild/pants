// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.unicode.unicodedep.consumer

import org.pantsbuild.testproject.unicode.unicodedep.provider.Provider


object Consumer {
  def main(args: Array[String]) = {
    println(Provider.ε)
  }
}
