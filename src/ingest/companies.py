"""The companies FilingLens indexes, plus the names people use for them.

Add a company here, re-run the download/parse/index steps, and it becomes searchable.
"""

COMPANIES = {
    "AAPL": {"name": "Apple", "aliases": ["apple"]},
    "MSFT": {"name": "Microsoft", "aliases": ["microsoft"]},
    "NVDA": {"name": "NVIDIA", "aliases": ["nvidia"]},
    "GOOGL": {"name": "Alphabet", "aliases": ["alphabet", "google"]},
    "AMZN": {"name": "Amazon", "aliases": ["amazon", "aws"]},
    "META": {"name": "Meta Platforms", "aliases": ["meta", "facebook", "instagram"]},
    "TSLA": {"name": "Tesla", "aliases": ["tesla"]},
    "JPM": {"name": "JPMorgan Chase", "aliases": ["jpmorgan", "jp morgan", "jpm", "chase"]},
    "V": {"name": "Visa", "aliases": ["visa"]},
    "JNJ": {"name": "Johnson & Johnson", "aliases": ["johnson & johnson", "johnson and johnson", "j&j", "jnj"]},
    "WMT": {"name": "Walmart", "aliases": ["walmart", "wal-mart"]},
    "NFLX": {"name": "Netflix", "aliases": ["netflix"]},
}

FILINGS_PER_COMPANY = 3

# 10-K "Items" and their plain-English names.
SECTION_NAMES = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Common Equity",
    "6": "Reserved",
    "7": "Management's Discussion and Analysis",
    "7A": "Market Risk Disclosures",
    "8": "Financial Statements",
    "9": "Changes in Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Foreign Jurisdiction Disclosure",
    "10": "Directors and Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Relationships and Transactions",
    "14": "Accountant Fees",
    "15": "Exhibits",
    "16": "Form 10-K Summary",
}
