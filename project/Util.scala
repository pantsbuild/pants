/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import sbt._
import sbt.inc.Analysis

object Util {
  def copyDirectory(source: File, target: File, overwrite: Boolean = false, preserveLastModified: Boolean = false, setExecutable: Boolean = false): Set[File] = {
    val sources = (source ***) x rebase(source, target)
    copyMapped(sources, overwrite, preserveLastModified, setExecutable)
  }

  def copyFlat(files: Traversable[File], target: File, overwrite: Boolean = false, preserveLastModified: Boolean = false, setExecutable: Boolean = false): Set[File] = {
    IO.createDirectory(target)
    val sources = files map { f => (f, target / f.name) }
    copyMapped(sources, overwrite, preserveLastModified, setExecutable)
  }

  def copyMapped(sources: Traversable[(File, File)], overwrite: Boolean = false, preserveLastModified: Boolean = false, setExecutable: Boolean = false): Set[File] = {
    sources map { Function.tupled(copy(overwrite, preserveLastModified, setExecutable)) } toSet
  }

  def copy(overwrite: Boolean, preserveLastModified: Boolean, setExecutable: Boolean)(source: File, target: File): File = {
    if (overwrite || !target.exists || source.lastModified > target.lastModified) {
      if (source.isDirectory) IO.createDirectory(target)
      else {
        IO.createDirectory(target.getParentFile)
        IO.copyFile(source, target, preserveLastModified)
        if (setExecutable) target.setExecutable(source.canExecute, false)
      }
    }
    target
  }

  def environment(property: String, env: String): Option[String] =
    Option(System.getProperty(property)) orElse Option(System.getenv(env))

  def lastCompile(analysis: Analysis): Long = {
    val times = analysis.apis.internal.values.map(_.compilation.startTime)
    if( times.isEmpty) 0L else times.max
  }
}
