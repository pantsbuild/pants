import logging
from pants.backend.experimental.audit.audit import rules as audit_rules
from pants.backend.experimental.audit.pip_audit_rule import rules as pip_audit_rules


logger = logging.getLogger(__name__)


def rules():
    return (
        *audit_rules(),
        *pip_audit_rules(),
    )