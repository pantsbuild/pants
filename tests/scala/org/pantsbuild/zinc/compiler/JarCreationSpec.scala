package org.pantsbuild.zinc.compiler

import java.io.File
import java.nio.file.{Path, Paths}
import scala.collection.mutable

import sbt.io.IO

import org.junit.runner.RunWith
import org.scalatest.WordSpec
import org.scalatest.junit.JUnitRunner
import org.scalatest.MustMatchers

@RunWith(classOf[JUnitRunner])
class JarCreationSpec extends WordSpec with MustMatchers {
  "JarCreationWithoutClasses" should {
    "succeed when input classes are provided" in {
      IO.withTemporaryDirectory { tempDir =>
        val filePaths = new mutable.TreeSet[Path]()
        val jarOutputPath = Paths.get(tempDir.toString, "spec-empty-output.jar")
        OutputUtils.createJar(filePaths, jarOutputPath, System.currentTimeMillis())
        OutputUtils.existsClass(jarOutputPath, "NonExistent.class") must be(false)
      }
    }
  }
  "JarCreationWithClasses" should {
    "succeed when input classes are provided" in {
      IO.withTemporaryDirectory { tempDir =>

        val tempDirPath = tempDir.toString
        val tempFile = File.createTempFile(tempDirPath, "Clazz.class")
        val filePaths = mutable.TreeSet(tempFile.toPath)
        val jarOutputPath = Paths.get(tempDirPath.toString, "spec-valid-output.jar")

        OutputUtils.createJar(filePaths, jarOutputPath, System.currentTimeMillis())
        OutputUtils.existsClass(jarOutputPath, tempFile.toString) must be(true)
      }
    }
  }
}

