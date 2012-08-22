/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.zinc

import java.io.File
import sbt.Relation
import sbt.inc.Analysis

object SbtAnalysis {

  /**
   * Print readable analysis outputs, if configured.
   */
  def printOutputs(analysis: Analysis, outputRelations: Option[File], outputProducts: Option[File], cwd: Option[File], classesDirectory: File): Unit = {
    printRelations(analysis, outputRelations, cwd)
    printProducts(analysis, outputProducts, classesDirectory)
  }

  /**
   * Print analysis relations to file.
   */
  def printRelations(analysis: Analysis, output: Option[File], cwd: Option[File]): Unit = {
    for (file <- output) {
      val userDir = (cwd getOrElse Setup.Defaults.userDir) + "/"
      def noCwd(path: String) = path stripPrefix userDir
      def keyValue(kv: (Any, Any)) = "   " + noCwd(kv._1.toString) + " -> " + noCwd(kv._2.toString)
      def relation(r: Relation[_, _]) = (r.all.toSeq map keyValue).sorted.mkString("\n")
      import analysis.relations.{ srcProd, binaryDep, internalSrcDep, externalDep, classes }
      val relationStrings = Seq(srcProd, binaryDep, internalSrcDep, externalDep, classes) map relation
      val output = """
        |products:
        |%s
        |binary dependencies:
        |%s
        |source dependencies:
        |%s
        |external dependencies:
        |%s
        |class names:
        |%s
        """.trim.stripMargin.format(relationStrings: _*)
      sbt.IO.write(file, output)
    }
  }

  /**
   * Print just source products to file, relative to classes directory.
   */
  def printProducts(analysis: Analysis, output: Option[File], classesDirectory: File): Unit = {
    for (file <- output) {
      def relative(path: String) = Util.relativize(classesDirectory, new File(path))
      def keyValue(kv: (Any, Any)) = relative(kv._1.toString) + " -> " + relative(kv._2.toString)
      val output = (analysis.relations.srcProd.all.toSeq map keyValue).sorted.mkString("\n")
      sbt.IO.write(file, output)
    }
  }
}
