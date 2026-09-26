"""Step 1: download 10-K filings from SEC EDGAR.

Run:  python -m src.ingest.download
Saves HTML files to data/raw/ and a manifest.json describing each one.
"""
import json
import sys
import time
from datetime import date, datetime

from src.config import RAW_DIR, settings
from src.ingest.companies import COMPANIES, FILINGS_PER_COMPANY


def _to_date(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def main() -> None:
    if not settings.sec_identity:
        sys.exit(
            "SEC_IDENTITY is empty. Add it to your .env file, e.g.\n"
            'SEC_IDENTITY="Your Name your.email@example.com"\n'
            "The SEC blocks downloads that don't identify who is asking."
        )

    try:
        from edgar import Company, set_identity
    except ImportError:
        sys.exit("edgartools is not installed. Run: pip install -r requirements-ingest.txt")

    set_identity(settings.sec_identity)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    known = {m["file"] for m in manifest}

    for ticker, info in COMPANIES.items():
        try:
            company = Company(ticker)
            filings = company.get_filings(form="10-K").latest(FILINGS_PER_COMPANY + 3)
            if filings is None:
                print(f"  none  {ticker}: no 10-K filings found")
                continue
            if not hasattr(filings, "__iter__"):  # latest() returns a single filing when only one exists
                filings = [filings]
            saved = 0
            for f in filings:
                if saved >= FILINGS_PER_COMPANY:
                    break
                if getattr(f, "form", "10-K") != "10-K":  # skip amendments (10-K/A)
                    continue
                filing_date = _to_date(getattr(f, "filing_date", None))
                period = _to_date(getattr(f, "period_of_report", None) or getattr(f, "report_date", None))
                fiscal_year = int((period or filing_date)[:4])
                fname = f"{ticker}_{fiscal_year}.html"
                saved += 1
                if fname in known:
                    print(f"  have  {fname}")
                    continue
                html = f.html()
                if not html:
                    print(f"  skip  {ticker} {filing_date}: no HTML document")
                    saved -= 1
                    continue
                (RAW_DIR / fname).write_text(html, encoding="utf-8")
                manifest.append(
                    {
                        "file": fname,
                        "ticker": ticker,
                        "company": info["name"],
                        "fiscal_year": fiscal_year,
                        "filing_date": filing_date,
                        "period_of_report": period,
                        "accession_no": getattr(f, "accession_no", None),
                    }
                )
                known.add(fname)
                manifest_path.write_text(json.dumps(manifest, indent=2))
                print(f"  saved {fname}  ({len(html) // 1024} KB)")
                time.sleep(0.5)  # stay well under the SEC's 10 requests/second limit
        except Exception as exc:  # keep going if one company fails
            print(f"  FAILED {ticker}: {exc}")

    print(f"\nDone. {len(manifest)} filings listed in {manifest_path}")


if __name__ == "__main__":
    main()
