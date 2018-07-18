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

object OutputUtils {

  /**
   * Sort the contents of the `dir` in lexicographic order.
   *
   * @param dir File handle containing the contents to sort
   * @return sorted set of all paths within the `dir`
   */
  def sort(dir:File): mutable.TreeSet[(Path, Boolean)] = {
    val sorted = new mutable.TreeSet[(Path, Boolean)]()

    val fileSortVisitor = new SimpleFileVisitor[Path]() {
      override def preVisitDirectory(path: Path, attrs: BasicFileAttributes): FileVisitResult = {
        sorted.add(path, false)
        FileVisitResult.CONTINUE
      }

      override def visitFile(path: Path, attrs: BasicFileAttributes): FileVisitResult = {
        sorted.add(path, true)
        FileVisitResult.CONTINUE
      }
    }

    Files.walkFileTree(dir.toPath, fileSortVisitor)
    sorted
  }

  def relativize(base: String, path: Path): String = {
    new File(base.toString).toURI().relativize(new File(path.toString).toURI()).getPath()
  }

  /**
   * Create a JAR of of filePaths provided.
   *
   * @param filePaths set of all paths to be added to the JAR
   * @param outputJarPath Absolute Path to the output JAR being created
   * @param jarEntryTime time to be set for each JAR entry
   */
  def createJar(
    base: String, filePaths: mutable.TreeSet[(Path, Boolean)], outputJarPath: Path, jarEntryTime: Long) {

    val target = new JarOutputStream(Files.newOutputStream(outputJarPath))

    def addToJar(source: (Path, Boolean), entryName: String): FileVisitResult = {
      val jarEntry = new JarEntry(entryName)
      // setting jarEntry time to a fixed value for all entries within the jar so that jars are
      // byte-for-byte reproducible.
      jarEntry.setTime(jarEntryTime)

      target.putNextEntry(jarEntry)
      if (source._2) {
        Files.copy(source._1, target)
      }
      target.closeEntry()
      FileVisitResult.CONTINUE
    }

    val pathToName = filePaths.zipWithIndex.map{case(k, v) => (k, relativize(base, k._1))}.toMap
    pathToName.map(e => addToJar(e._1, e._2))
    target.close()
  }

  /**
   * Jar the contents of output classes (settings.classesDirectory) and copy to settings.outputJar
   *
   */
  def createClassesJar(classesDirectory: File, outputJarPath: Path, jarCreationTime: Long) = {

    // Sort the contents of the classesDirectory for deterministic jar creation
    val sortedClasses = sort(classesDirectory)

    createJar(classesDirectory.toString, sortedClasses, outputJarPath, jarCreationTime)
  }

  /**
   * Determines if a file exists in a JAR provided.
   *
   * @param jarPath Absolute Path to the JAR being inspected
   * @param fileName Name of the file, the existence of which is to be inspected
   * @return
   */
  def existsClass(jarPath: Path, fileName: String): Boolean = {
    var jis: JarInputStream = null
    var found = false
    try {
      jis = new JarInputStream(Files.newInputStream(jarPath))

      @tailrec
      def findClass(entry: JarEntry): Boolean = entry match {
        case null =>
          false
        case entry if entry.getName == fileName =>
          true
        case _ =>
          findClass(jis.getNextJarEntry)
      }

      found = findClass(jis.getNextJarEntry)
    } finally {
      jis.close()
    }
    found
  }
}
