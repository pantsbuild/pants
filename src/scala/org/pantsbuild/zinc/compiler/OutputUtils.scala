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
  def sort(dir: File): mutable.TreeSet[Path] = {
    val sorted = new mutable.TreeSet[Path]()

    val fileSortVisitor = new SimpleFileVisitor[Path]() {
      override def preVisitDirectory(
          path: Path,
          attrs: BasicFileAttributes): FileVisitResult = {
        sorted.add(path)
        FileVisitResult.CONTINUE
      }

      override def visitFile(path: Path,
                             attrs: BasicFileAttributes): FileVisitResult = {
        sorted.add(path)
        FileVisitResult.CONTINUE
      }
    }

    Files.walkFileTree(dir.toPath, fileSortVisitor)
    sorted
  }

  def relativize(base: String, path: Path): String = {
    new File(base.toString)
      .toURI()
      .relativize(new File(path.toString).toURI())
      .getPath()
  }

  /**
    * Create a JAR from the file and directory paths provided.
    *
    * @param paths set of all paths to be added to the JAR
    * @param outputJarPath Absolute Path to the output JAR being created
    * @param jarEntryTime time to be set for each JAR entry
    */
  def createJar(base: String,
                paths: mutable.TreeSet[Path],
                outputJarPath: Path,
                jarEntryTime: Long) {

    val target = new JarOutputStream(Files.newOutputStream(outputJarPath))

    def jarEntry(name: String): JarEntry = {
      val jarEntry = new JarEntry(name)
      // setting jarEntry time to a fixed value for all entries within the jar so that jars are
      // byte-for-byte reproducible.
      jarEntry.setTime(jarEntryTime)
      jarEntry
    }

    def addToJar(source: Path, entryName: String) {
      if (source.toFile.isDirectory) {
        target.putNextEntry(
          jarEntry(if (entryName.endsWith("/")) entryName else entryName + '/'))
      } else {
        target.putNextEntry(jarEntry(entryName))
        Files.copy(source, target)
      }
      target.closeEntry()
    }

    for (path <- paths;
         relativePath = relativize(base, path)
         if relativePath.nonEmpty) {
      addToJar(path, relativePath)
    }
    target.close()
  }

  /**
    * Jar the contents of output classes (settings.classesDirectory) and copy to settings.outputJar
    *
    */
  def createClassesJar(classesDirectory: File,
                       outputJarPath: Path,
                       jarCreationTime: Long) = {

    // Sort the contents of the classesDirectory for deterministic jar creation
    val sortedClasses = sort(classesDirectory)

    createJar(classesDirectory.toString,
              sortedClasses,
              outputJarPath,
              jarCreationTime)
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
