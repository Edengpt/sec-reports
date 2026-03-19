import re

KEYWORDS = [
    # Contract / Agreement
    "material definitive agreement",
    "entered into a contract",
    "entered into an agreement",
    "signed a contract",
    "signed an agreement",
    "executed a contract",
    "executed an agreement",
    "supply agreement",
    "supply contract",
    "service agreement",
    "master services agreement",
    "purchase agreement",
    "license agreement",
    "licensing agreement",
    # Awards / Wins
    "contract award",
    "awarded a contract",
    "won a contract",
    "selected as",
    "chosen as a vendor",
    "chosen as a supplier",
    # Government / Defense
    "government contract",
    "federal contract",
    "defense contract",
    "task order",
    "indefinite delivery",
    # Orders
    "purchase order",
    "received an order",
    "received orders",
    "new order",
    "order backlog",
    # Customer / Partnership
    "new customer",
    "new client",
    "strategic partnership",
    "strategic alliance",
    "collaboration agreement",
    "joint venture",
]

# Compile patterns for efficiency (case-insensitive)
_patterns = [(kw, re.compile(re.escape(kw), re.IGNORECASE)) for kw in KEYWORDS]


def filter_report(text):
    """Check if text matches any keywords. Returns list of matched keywords."""
    if not text:
        return []
    matched = []
    for kw, pattern in _patterns:
        if pattern.search(text):
            matched.append(kw)
    return matched
