/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import java.io.File
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.{FileVisitResult, Files, Path, Paths, SimpleFileVisitor}
import java.util.jar.{JarEntry, JarInputStream, JarOutputStream}
import scala.annotation.tailrec
import scala.collection.mutable
import scala.util.Try

object OutputUtils {

  /**
   * Sort the contents of the `dir` in lexicographic order.
   *
   * @param dir File handle containing the contents to sort
   * @return sorted set of all paths within the `dir`
   */
  def sort(dir:File): mutable.TreeSet[Path] = {
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

    Files.walkFileTree(dir.toPath, fileSortVisitor)
    sorted
  }

  /**
   * Create a JAR of of filePaths provided.
   *
   * @param filePaths set of all paths to be added to the JAR
   * @param outputJarPath Path to the output JAR to be created
   * @param jarEntryTime time to be set for each JAR entry
   */
  def createJar(filePaths: mutable.TreeSet[Path], outputJarPath: Path, jarEntryTime: Long) {

    val target = new JarOutputStream(Files.newOutputStream(outputJarPath))

    def addToJar(source: Path): FileVisitResult = {
      val jarEntry = new JarEntry(source.toString)
      // setting jarEntry time to a fixed value for all entries within the jar so that jars are
      // byte-for-byte reproducible.
      jarEntry.setTime(jarEntryTime)

      target.putNextEntry(jarEntry)
      Files.copy(source, target)
      target.closeEntry()
      FileVisitResult.CONTINUE
    }

    filePaths.map(addToJar(_))
    target.close()
  }

  /**
   * Jar the contents of output classes (settings.classesDirectory) and copy to settings.outputJar
   *
   */
  def createClassesJar(classesDirectory: File, outputJarPath: Path, jarCreationTime: Long) = {

    // Sort the contents of the classesDirectory for deterministic jar creation
    val sortedClasses = sort(classesDirectory)

    createJar(sortedClasses, outputJarPath, jarCreationTime)
  }

  /**
   * Determines if a Class exists in a JAR provided.
   *
   * @param jarPath Absolute Path to the JAR being inspected
   * @param clazz Name of the Class, the existence of which is to be inspected
   * @return
   */
  def existsClass(jarPath: Path, clazz: String): Boolean = {
    val jis = new JarInputStream(Files.newInputStream(jarPath))
    @tailrec
    def findClass(entry: JarEntry): Boolean = entry match {
      case null =>
        false
      case entry if entry.getName == clazz =>
        true
      case _ =>
        findClass(jis.getNextJarEntry)
    }
    findClass(jis.getNextJarEntry)
  }
}
