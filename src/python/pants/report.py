import uuid

from humbug.consent import environment_variable_opt_out, HumbugConsent, no
from humbug.report import Reporter

BUGOUT_ACCESS_TOKEN: str = "3ae76900-9a68-4a87-a127-7c9f179d7272"
BUGOUT_JOURNAL_ID: str = "801e9b3c-6b03-40a7-870f-5b25d326da66"

# To opt out of reporting, set PANTS_REPORTING_ENABLED=0 in your environment.
reporting_consent: HumbugConsent = HumbugConsent(environment_variable_opt_out("PANTS_REPORTING_ENABLED", no))

session_id: str = str(uuid.uuid4())
reporter: Reporter = Reporter(
    "pantsbuild/pants",
    reporting_consent,
    session_id=session_id,
    bugout_token=BUGOUT_ACCESS_TOKEN,
    bugout_journal_id=BUGOUT_JOURNAL_ID,
    timeout_seconds=5,
    )
