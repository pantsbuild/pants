// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.cp_directories

import collection.JavaConverters._

import com.google.common.reflect.ClassPath

import org.junit.runner.RunWith
import org.scalatest.WordSpec
import org.scalatest.junit.JUnitRunner
import org.scalatest.MustMatchers

/** A test that confirms it can list the classes in its own package to find itself. */
@RunWith(classOf[JUnitRunner])
class ClasspathDirectories extends WordSpec with MustMatchers {
  "ClasspathDirectories" should {
    "be able to find itself" in {
      val thisClass = this.getClass.getCanonicalName
      val thisPackage = thisClass.split('.').dropRight(1).mkString(".")
      val classes =
        ClassPath.from(this.getClass.getClassLoader)
          .getTopLevelClasses(thisPackage)
      classes.asScala.map(_.toString) must contain(thisClass)
    }
  }
}
