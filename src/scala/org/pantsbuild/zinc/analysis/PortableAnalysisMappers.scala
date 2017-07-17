/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.analysis

import java.io.File
import java.nio.file.Path

import xsbti.compile.analysis.{GenericMapper, ReadMapper, ReadWriteMappers, WriteMapper}

import xsbti.compile.MiniSetup
import xsbti.compile.analysis.Stamp


/**
 * Given a Set of Path bases and destination bases, adapts written analysis to rewrite
 * all of the bases.
 *
 * Intended usecase is to rebase each distinct non-portable base path contained in the analysis:
 * in pants this is generally
 *   1) the buildroot
 *   2) the workdir (generally named `.pants.d`, but not always located under the buildroot)
 *   3) the base of the JVM that is in use
 */
object PortableAnalysisMappers {
  def create(rebaseMap: Map[File, File]): ReadWriteMappers = {
    val rebases =
      rebaseMap
        .toSeq
        .map {
          case (k, v) => (k.toPath, v.toPath)
        }
        .toSet
    val forWrite = mkFileRebaser(rebases)
    val forRead = mkFileRebaser(rebases.map { case (src, dst) => (dst, src) })
    new ReadWriteMappers(PortableReadMapper(forRead), PortableWriteMapper(forWrite))
  }

  private def mkFileRebaser(rebases: Set[(Path, Path)]): File => File = {
    // Sort the rebases from longest to shortest (to ensure that a prefix is rebased
    // before a suffix).
    val orderedRebases =
      rebases.toSeq.sortBy {
        case (path, slug) => -path.toString.size
      }
    val rebaser: File => File = { f =>
      val p = f.toPath
      // Attempt each rebase in length order, applying the longest one that matches.
      orderedRebases
        .collectFirst {
          case (from, to) if p.startsWith(from) =>
            to.resolve(from.relativize(p)).toFile
        }
        .getOrElse(f)
    }
    rebaser
  }
}

case class PortableReadMapper(mapper: File => File) extends PortableMapper with ReadMapper
case class PortableWriteMapper(mapper: File => File) extends PortableMapper with WriteMapper

trait PortableMapper extends GenericMapper {
  def mapper: File => File

  def mapSourceFile(x: File): File = mapper(x)
  def mapBinaryFile(x: File): File = mapper(x)
  def mapProductFile(x: File): File = mapper(x)
  def mapOutputDir(x: File): File = mapper(x)
  def mapSourceDir(x: File): File = mapper(x)
  def mapClasspathEntry(x: File): File = mapper(x)

  // TODO: Determine whether the rest of these need to be overridden in practice.
  def mapJavacOption(x: String): String = x
  def mapScalacOption(x: String): String = x
  def mapBinaryStamp(f: File, x: Stamp): Stamp = x
  def mapSourceStamp(f: File, x: Stamp): Stamp = x
  def mapProductStamp(f: File, x: Stamp): Stamp = x
  def mapMiniSetup(x: MiniSetup): MiniSetup = x
}
