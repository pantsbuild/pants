package org.pantsbuild.scoverage.report

import org.pantsbuild.zinc.options.OptionSet
import org.pantsbuild.zinc.options.ArgumentOption

/**
 * All parsed command-line options.
 */
case class Settings(
  help: Boolean                           = false,
  loadDataDir: Boolean                    = false,
  measurementsDirPath: String             = "",
  reportDirPath: String                   = "",
  sourceDirPath: String                   = ".",
  dataDirPath: String                     = "",
  writeHtmlReport: Boolean                = true,
  writeXmlReport: Boolean                 = true,
  writeXmlDebug: Boolean                  = false,
  cleanOldReports: Boolean                = true,
  targetFilters:Seq[String]               = Seq()
)

object Settings extends OptionSet2[Settings] {
  override def empty = Settings()

  override val options = Seq(
    boolean(  ("-help", "-h"),                 "Print this usage message",
      (s: Settings) => s.copy(help = true)),

    boolean( "-loadDataDir",                   "Load a single measurements directory instead of aggregating coverage reports. Must pass in `dataDirPath <dir>`",
      (s: Settings) => s.copy(loadDataDir = true)),

    string( "-measurementsDirPath", "dir",       "Directory where all scoverage measurements data is stored.",
      (s: Settings, dir: String) => s.copy(measurementsDirPath = dir)),

    string( "-reportDirPath", "dir",            "Target output directory to place the reports.",
      (s: Settings, dir: String) => s.copy(reportDirPath = dir)),

    string( "-sourceDirPath", "dir",            "Directory containing the project sources.",
      (s: Settings, dir: String) => s.copy(sourceDirPath = dir)),

    string( "-dataDirPath", "dir",               "Scoverage data file directory to be used in case report needed for single measurements " +
      "directory. Must set `loadDataDir` to use this options.",
      (s: Settings, dir: String) => s.copy(dataDirPath = dir)),

    boolean( "-writeHtmlReport",                  "Write the HTML version of the coverage report.",
      (s: Settings) => s.copy(writeHtmlReport = true)),

    boolean( "-writeXmlReport",                   "Write the XML version of the coverage report.",
      (s: Settings) => s.copy(writeXmlReport = true)),

    boolean( "-writeXmlDebug",                    "Write debug information to the XML version of the coverage report.",
      (s: Settings) => s.copy(writeXmlDebug = true)),

    boolean( "-cleanOldReports",                   "Delete any existing reports directory prior to writing reports.",
      (s: Settings) => s.copy(cleanOldReports = true)),

    stringList("-targetFilters", "filters",         "Directory names for which report has to be generated.",
      (s:Settings, filters: Seq[String]) => s.copy(targetFilters = filters)),

  )
}

trait OptionSet2[T] extends OptionSet[T]{
  def stringList(opt: String, arg: String, desc: String, action: (T, Seq[String]) => T) = new StringListOption[T](Seq(opt), arg, desc, action)
}


class StringListOption[Context](
  val options: Seq[String],
  val argument: String,
  val description: String,
  val action: (Context, Seq[String]) => Context)
  extends ArgumentOption[Seq[String], Context]{
  def parse(arg: String): Option[Seq[String]] = {
    val expanded = arg.split(",")
    Some(expanded)
  }
}
