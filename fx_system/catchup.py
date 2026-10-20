"""Pure eligibility check for the final verified M5 catch-up pass."""
from .provenance import key


def needs_m5_catchup(first_request, now, provenance):
    """Only retry if a newly closed, still-unverified M5 bar is required."""
    if type(first_request) is not int or type(now) is not int:
        return False
    expected_at_request=(first_request//300-1)*300
    expected_now=(now//300-1)*300
    return (expected_now>expected_at_request
            and provenance.get(key("m5",expected_now))!="Twelve Data")
