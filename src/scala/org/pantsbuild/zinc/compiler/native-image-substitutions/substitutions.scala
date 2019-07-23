package org.pantsbuild.zinc.compiler.substitutions.scala.tools.nsc

import java.io.File

final class Target_scala_tools_nsc_ast_TreeBrowsers$SwingBrowser {
  def browse(pName: String, units: List[AnyRef]): Unit = throw new RuntimeException("Swing currently unsupported in the native compiler.")
}

final class Target_sbt_io_IO$ {
  def getModifiedTimeOrZero(file: File): Long = file.lastModified()
  def setModifiedTimeOrFalse(file: File, mtime: Long): Boolean = file.setLastModified(mtime)
}
