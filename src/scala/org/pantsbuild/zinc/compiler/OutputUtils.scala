/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.{FileVisitResult, Files, Path, Paths, SimpleFileVisitor}
import java.util.jar.{JarEntry, JarOutputStream}
import scala.collection.mutable
import sbt.util.Logger

object OutputUtils {

  /**
   * Jar the contents of output classes (settings.classesDirectory) and copy to settings.outputJar
   */
  def createClassesJar(settings: Settings, log: Logger) = {
    val classesDirectory = settings.classesDirectory
    val sorted = new mutable.TreeSet[Path]()

    val fileSortVisitor = new SimpleFileVisitor[Path]() {
      override def preVisitDirectory(path: Path, attrs: BasicFileAttributes): FileVisitResult = {
        sorted.add(path)
        FileVisitResult.CONTINUE
      }
      override def visitFile(path: Path, attrs: BasicFileAttributes): FileVisitResult = {
        sorted.add(path)
        FileVisitResult.CONTINUE
      }
    }
    // Sort the contents of the classesDirectory in lexicographic order
    Files.walkFileTree(classesDirectory.toPath, fileSortVisitor)

    val jarPath = Paths.get(classesDirectory.toString, settings.outputJar.toString)
    val target = new JarOutputStream(Files.newOutputStream(jarPath))

    def createJar(source: Path): FileVisitResult = {
      val jarEntry = new JarEntry(source.toString)
      // setting jarEntry time to a fixed value for all entries within the jar for determinism
      // and so that jar are byte-for-byte reproducible.
      jarEntry.setTime(settings.creationTime)

      log.debug("Creating jar entry " + jarEntry + " for the file " + source)

      target.putNextEntry(jarEntry)
      Files.copy(source, target)
      target.closeEntry()
      FileVisitResult.CONTINUE
    }
    sorted.map(createJar(_))
  }
}
