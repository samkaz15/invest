"""Reports — the daily Markdown deliverable.

This layer formats stored artifacts and does nothing else: no analysis, no
score, no series the pipeline has not already written down. A report that
computes its own figures produces numbers nobody can reconcile with the
database, and the first time the two disagree neither is trustworthy.
"""

from mios.reports.daily import VERSION, DailyReport, write_report

__all__ = ["VERSION", "DailyReport", "write_report"]
