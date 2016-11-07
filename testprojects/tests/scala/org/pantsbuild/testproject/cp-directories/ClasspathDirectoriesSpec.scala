// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.cp_directories

import org.junit.runner.RunWith
import org.scalatest.WordSpec
import org.scalatest.junit.JUnitRunner
import org.scalatest.MustMatchers

/**
 * A test that confirms it can fetch the directory entry for its own package. This confirms
 * that the classpath provided to the test contains directories, which may not always be true
 * for jars.
 */
@RunWith(classOf[JUnitRunner])
class ClasspathDirectoriesSpec extends WordSpec with MustMatchers {
  val thisPackage = this.getClass.getCanonicalName.split('.').dropRight(1).mkString(".")

  "ClasspathDirectoriesSpec" should {
    "see its own package as a directory on the classpath" in {
      val packageResource = "/" + thisPackage.replace('.', '/')
      Option(this.getClass.getResource(packageResource)) mustBe defined
    }
  }
}
