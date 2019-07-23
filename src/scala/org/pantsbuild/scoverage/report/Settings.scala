package org.pantsbuild.scoverage.report

/**
 * All parsed command-line options.
 */
case class Settings(
  loadDataDir: Boolean = false,
  measurementsDirPath: String = "",
  reportDirPath: String = "",
  sourceDirPath: String = ".",
  dataDirPath: String = "",
  writeHtmlReport: Boolean = true,
  writeXmlReport: Boolean = true,
  writeXmlDebug: Boolean = false,
  cleanOldReports: Boolean = true,
  targetFilters: Seq[String] = Seq())

object Settings {

  val parser1 = new scopt.OptionParser[Settings]("scoverage") {
    head("scoverageReportGenerator")

    help("help")
      .text("Print this usage message.")

    opt[Unit]("loadDataDir")
      .action((_, s: Settings) => s.copy(loadDataDir = true))
      .text("Load a single measurements directory instead of aggregating coverage reports. Must pass in `dataDirPath <dir>`")

    opt[String]("measurementsDirPath")
      .action((dir: String, s: Settings) => s.copy(measurementsDirPath = dir))
      .text("Directory where all scoverage measurements data is stored.")

    opt[String]("reportDirPath")
      .action((dir: String, s: Settings) => s.copy(reportDirPath = dir))
      .text("Target output directory to place the reports.")

    opt[String]("sourceDirPath")
      .action((dir: String, s: Settings) => s.copy(sourceDirPath = dir))
      .text("Directory containing the project sources.")

    opt[String]("dataDirPath")
      .action((dir: String, s: Settings) => s.copy(dataDirPath = dir))
      .text("Scoverage data file directory to be used in case report needed for single measurements " +
        "directory. Must set `loadDataDir` to use this options.")

    opt[Unit]("writeHtmlReport")
      .action((_, s: Settings) => s.copy(writeHtmlReport = true))
      .text("Write the HTML version of the coverage report.")

    opt[Unit]("writeXmlReport")
      .action((_, s: Settings) => s.copy(writeXmlReport = true))
      .text("Write the XML version of the coverage report.")

    opt[Unit]("writeXmlDebug")
      .action((_, s: Settings) => s.copy(writeXmlDebug = true))
      .text("Write debug information to the XML version of the coverage report.")

    opt[Unit]("cleanOldReports")
      .action((_, s: Settings) => s.copy(cleanOldReports = true))
      .text("Delete any existing reports directory prior to writing reports.")

    opt[Seq[String]]("targetFilters")
      .action((f: Seq[String], s: Settings) => s.copy(targetFilters = f))
      .text("Directory names for which report has to be generated.")
  }
}
