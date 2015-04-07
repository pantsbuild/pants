// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.unicode.shapeless

import shapeless.~?>

/**
 * References a class in an external dependency with a non-ascii encodable unicode name.
 */
object ShapelessExample {

  /**
   * Validates the `~?>.λ` type is accessible, returning "shapeless success" if so.
   */
  def greek(): String = {
    val riddle = new ~?>[List, List]()
    val witness: ~?>[List, List]#λ[List[String], List[String]] =
      ~?>.witness[List, List, String](riddle)
    "shapeless success"
  }
}
