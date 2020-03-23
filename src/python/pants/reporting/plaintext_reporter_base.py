# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.reporting.reporter import Reporter


class PlainTextReporterBase(Reporter):
    """Base class for plain-text reporting to stdout."""

    def generate_epilog(self, settings):
        ret = ""
        if settings.timing:
            ret += "\nCumulative Timings\n==================\n{}\n".format(
                self._format_aggregated_timings(self.run_tracker.cumulative_timings)
            )
            ret += "\nSelf Timings\n============\n{}\n".format(
                self._format_aggregated_timings(self.run_tracker.self_timings)
            )

            ret += "\nCritical Path Timings\n=====================\n{}\n".format(
                self._format_aggregated_timings(self.run_tracker.get_critical_path_timings())
            )
        if settings.cache_stats:
            ret += "\nCache Stats\n===========\n{}\n".format(
                self._format_artifact_cache_stats(self.run_tracker.artifact_cache_stats)
            )
        ret += "\n"
        return ret

    def _format_aggregated_timings(self, aggregated_timings):
        return "\n".join(["{timing:.3f} {label}".format(**x) for x in aggregated_timings.get_all()])

    def _format_artifact_cache_stats(self, artifact_cache_stats):
        stats = artifact_cache_stats.get_all()
        return (
            "No artifact cache reads."
            if not stats
            else "\n".join(
                ["{cache_name} - Hits: {num_hits} Misses: {num_misses}".format(**x) for x in stats]
            )
        )
