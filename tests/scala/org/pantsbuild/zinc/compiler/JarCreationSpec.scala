package org.pantsbuild.zinc.compiler

import sbt.io.IO

import java.io.File
import java.nio.file.{Files, Path, Paths}
import scala.collection.mutable
import org.junit.runner.RunWith
import org.scalatest.WordSpec
import org.scalatest.junit.JUnitRunner
import org.scalatest.MustMatchers

@RunWith(classOf[JUnitRunner])
class JarCreationSpec extends WordSpec with MustMatchers {
  "JarCreationWithoutClasses" should {
    "succeed when input classes are not provided" in {
      IO.withTemporaryDirectory { tempInputDir =>
        val filePaths = new mutable.TreeSet[Path]()

        IO.withTemporaryDirectory { tempOutputDir =>
          val jarOutputPath = Paths.get(tempOutputDir.toString, "spec-empty-output.jar")

          OutputUtils.createJar(tempInputDir.toString, filePaths, jarOutputPath, System.currentTimeMillis())
          OutputUtils.existsClass(jarOutputPath, "NonExistent.class") must be(false)
        }
      }
    }
  }
  
  "JarCreationWithClasses" should {
    "succeed when input classes are provided" in {
      IO.withTemporaryDirectory { tempInputDir =>
        val tempFile = File.createTempFile("Temp", ".class", tempInputDir)
        val filePaths = mutable.TreeSet(tempFile.toPath)

        IO.withTemporaryDirectory { tempOutputDir =>
          val jarOutputPath = Paths.get(tempOutputDir.toString, "spec-valid-output.jar")

          OutputUtils.createJar(tempInputDir.toString, filePaths, jarOutputPath, System.currentTimeMillis())
          OutputUtils.existsClass(jarOutputPath, tempFile.toString) must be(false)
          OutputUtils.existsClass(jarOutputPath, OutputUtils.relativize(tempInputDir.toString, tempFile.toPath)) must be(true)
        }
      }
    }
  }

  "JarCreationWithNestedClasses" should {
    "succeed when nested input directory and classes are provided" in {
      IO.withTemporaryDirectory { tempInputDir =>
        val nestedTempDir = Files.createTempDirectory(tempInputDir.toPath, "tmp")
        val nestedTempClass = File.createTempFile("NestedTemp", ".class", nestedTempDir.toFile)
        val filePaths = mutable.TreeSet(nestedTempDir, nestedTempClass.toPath)
        IO.withTemporaryDirectory { tempOutputDir =>
          val jarOutputPath = Paths.get(tempOutputDir.toString, "spec-valid-output.jar")

          OutputUtils.createJar(tempInputDir.toString, filePaths, jarOutputPath, System.currentTimeMillis())
          OutputUtils.existsClass(jarOutputPath, OutputUtils.relativize(tempInputDir.toString, nestedTempDir)) must be(true)
          OutputUtils.existsClass(jarOutputPath, OutputUtils.relativize(tempInputDir.toString, nestedTempClass.toPath)) must be(true)
        }
      }
    }
  }
}

