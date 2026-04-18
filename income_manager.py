# income_manager.py
# Hayeong's income generation management system.
#
# Handles:
#   - Opportunity research and proposal generation
#   - Product tracking across all income streams
#   - Revenue logging toward workstation goal
#   - Platform management (where products are listed)
#   - Autonomous task scheduling for recurring income work
#
# The proposal loop:
#   1. Hayeong researches → writes proposal
#   2. Proposal stored here, James notified via email/Discord
#   3. James approves/rejects → Hayeong executes or archives
#   4. After execution, product tracked here
#   5. Revenue logged when sales come in

import csv
import json
import uuid
from pathlib import Path
from datetime import datetime, date

BASE_DIR      = Path(__file__).parent
INCOME_FILE   = BASE_DIR / "income_log.json"
PRODUCTS_FILE = BASE_DIR / "products_log.json"

EARNINGS_DIR  = BASE_DIR / "logs" / "earnings"
EARNINGS_CSV  = EARNINGS_DIR / "earnings_log.csv"

CSV_HEADERS = [
    "date", "timestamp", "sale_id", "product_id", "product_title",
    "stream", "platform", "gross_amount", "platform_fee", "net_amount", "notes",
]

PLATFORM_FEES = {
    "Etsy":            0.15,   # ~15% combined (transaction + payment processing + listing)
    "Gumroad":         0.10,   # ~10% on free plan
    "Creative Market": 0.30,   # 30% commission
    "Patreon":         0.08,   # ~8% on Pro plan
    "Redbubble":       0.20,   # ~20% margin after base cost
    "Direct":          0.03,   # ~3% payment processing only (Stripe/PayPal)
    "Other":           0.00,   # unknown — log gross only, note manually
}

WORKSTATION_GOAL = 3000.00  # USD — update when real component research done

# ── Income stream categories ──
STREAM_DIGITAL_ART     = "digital_art"
STREAM_WRITING         = "writing_service"
STREAM_PROMPT_PACKS    = "prompt_packs"
STREAM_LIVE2D          = "live2d_models"
STREAM_APP_DEV         = "app_development"
STREAM_CODING_SERVICE  = "coding_service"
STREAM_AI_AGENTS       = "ai_agent_service"

# ── Proposal status ──
STATUS_PENDING   = "pending_james"
STATUS_APPROVED  = "approved"
STATUS_REJECTED  = "rejected"
STATUS_EXECUTING = "executing"
STATUS_COMPLETE  = "complete"
STATUS_LISTED    = "listed"


def _load(path: Path, default) -> dict | list:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _save(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class IncomeManager:
    """
    Manages Hayeong's income generation workflow.
    One instance shared across the system.
    """

    def __init__(self):
        self.income   = _load(INCOME_FILE,   {"entries": [], "total_earned": 0.0})
        self.products = _load(PRODUCTS_FILE, {"proposals": [], "active": [], "archived": []})

    # ─────────────────────────────────────────
    # PROPOSALS
    # ─────────────────────────────────────────

    def submit_proposal(
        self,
        title: str,
        stream: str,
        description: str,
        estimated_value: float = 0.0,
        platform: str = "",
        production_notes: str = "",
    ) -> dict:
        """
        Hayeong submits an income opportunity for James's review.
        Returns the proposal dict with its ID.
        """
        proposal = {
            "id":               str(uuid.uuid4())[:8],
            "title":            title,
            "stream":           stream,
            "description":      description,
            "estimated_value":  estimated_value,
            "platform":         platform,
            "production_notes": production_notes,
            "status":           STATUS_PENDING,
            "submitted":        datetime.now().isoformat(),
            "approved":         None,
            "completed":        None,
            "listed":           None,
            "actual_revenue":   0.0,
            "notes":            [],
        }
        self.products["proposals"].append(proposal)
        _save(PRODUCTS_FILE, self.products)
        return proposal

    def approve_proposal(self, proposal_id: str, james_note: str = "") -> bool:
        """James approves a proposal. Hayeong can now execute."""
        for p in self.products["proposals"]:
            if p["id"] == proposal_id:
                p["status"]   = STATUS_APPROVED
                p["approved"] = datetime.now().isoformat()
                if james_note:
                    p["notes"].append({"by": "james", "note": james_note,
                                       "at": datetime.now().isoformat()})
                _save(PRODUCTS_FILE, self.products)
                return True
        return False

    def reject_proposal(self, proposal_id: str, reason: str = "") -> bool:
        """James rejects a proposal. Move to archived."""
        for i, p in enumerate(self.products["proposals"]):
            if p["id"] == proposal_id:
                p["status"] = STATUS_REJECTED
                if reason:
                    p["notes"].append({"by": "james", "note": reason,
                                       "at": datetime.now().isoformat()})
                self.products["archived"].append(p)
                self.products["proposals"].pop(i)
                _save(PRODUCTS_FILE, self.products)
                return True
        return False

    def mark_executing(self, proposal_id: str) -> bool:
        """Hayeong starts working on an approved proposal."""
        for p in self.products["proposals"]:
            if p["id"] == proposal_id and p["status"] == STATUS_APPROVED:
                p["status"] = STATUS_EXECUTING
                _save(PRODUCTS_FILE, self.products)
                return True
        return False

    def mark_complete(self, proposal_id: str, output_path: str = "",
                      hayeong_note: str = "") -> bool:
        """
        Hayeong finished execution. Waiting for James's final review
        before submitting/listing.
        """
        for p in self.products["proposals"]:
            if p["id"] == proposal_id:
                p["status"]    = STATUS_COMPLETE
                p["completed"] = datetime.now().isoformat()
                if output_path:
                    p["output_path"] = output_path
                if hayeong_note:
                    p["notes"].append({"by": "hayeong", "note": hayeong_note,
                                       "at": datetime.now().isoformat()})
                _save(PRODUCTS_FILE, self.products)
                return True
        return False

    def mark_listed(self, proposal_id: str, listing_url: str = "",
                    platform: str = "") -> bool:
        """James approved the output. Product is now live."""
        for i, p in enumerate(self.products["proposals"]):
            if p["id"] == proposal_id and p["status"] == STATUS_COMPLETE:
                p["status"]      = STATUS_LISTED
                p["listed"]      = datetime.now().isoformat()
                p["listing_url"] = listing_url
                if platform:
                    p["platform"] = platform
                self.products["active"].append(p)
                self.products["proposals"].pop(i)
                _save(PRODUCTS_FILE, self.products)
                return True
        return False

    def get_pending_proposals(self) -> list:
        """Return all proposals waiting for James's review."""
        return [p for p in self.products["proposals"]
                if p["status"] == STATUS_PENDING]

    def get_approved_proposals(self) -> list:
        """Return all proposals James approved — ready for Hayeong to execute."""
        return [p for p in self.products["proposals"]
                if p["status"] in (STATUS_APPROVED, STATUS_EXECUTING)]

    def get_proposal_by_id(self, proposal_id: str) -> dict | None:
        """Find a proposal by ID across all lists."""
        for p in self.products["proposals"] + self.products["active"] + self.products["archived"]:
            if p["id"] == proposal_id:
                return p
        return None

    # ─────────────────────────────────────────
    # REVENUE LOGGING
    # ─────────────────────────────────────────

    def log_sale(self, product_id: str, amount: float,
                 platform: str = "", notes: str = "") -> dict:
        """Log a sale. Updates JSON log, CSV file, and workstation goal total."""
        entry = {
            "id":         str(uuid.uuid4())[:8],
            "product_id": product_id,
            "amount":     amount,
            "platform":   platform,
            "notes":      notes,
            "date":       date.today().isoformat(),
            "timestamp":  datetime.now().isoformat(),
        }
        self.income["entries"].append(entry)
        self.income["total_earned"] = round(
            self.income["total_earned"] + amount, 2)
        _save(INCOME_FILE, self.income)

        # Find product details for CSV row, update actual_revenue
        product_title = "Unknown"
        stream        = "unknown"
        for p in self.products["active"]:
            if p["id"] == product_id:
                product_title       = p.get("title", "Unknown")
                stream              = p.get("stream", "unknown")
                p["actual_revenue"] = round(p.get("actual_revenue", 0.0) + amount, 2)
                break
        _save(PRODUCTS_FILE, self.products)

        # Write to CSV — always, automatically
        self._write_csv_row(entry, product_title, stream, platform, amount)

        return entry

    # ─────────────────────────────────────────
    # CSV LOGGING
    # ─────────────────────────────────────────

    def _ensure_csv(self):
        """Create CSV file with headers if it doesn't exist yet."""
        EARNINGS_DIR.mkdir(parents=True, exist_ok=True)
        if not EARNINGS_CSV.exists():
            with open(EARNINGS_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADERS)

    def _write_csv_row(self, entry: dict, product_title: str,
                       stream: str, platform: str, gross: float):
        """Append one sale row to the CSV."""
        self._ensure_csv()
        fee_rate   = PLATFORM_FEES.get(platform, 0.0)
        fee_amount = round(gross * fee_rate, 2)
        net_amount = round(gross - fee_amount, 2)
        row = [
            entry["date"],
            entry["timestamp"],
            entry["id"],
            entry["product_id"],
            product_title,
            stream,
            platform,
            f"{gross:.2f}",
            f"{fee_amount:.2f}",
            f"{net_amount:.2f}",
            entry.get("notes", ""),
        ]
        with open(EARNINGS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def generate_monthly_summary(self, year: int = None, month: int = None) -> str:
        """
        Generate a monthly summary CSV from the earnings log.
        Defaults to the current month.
        Returns the path to the generated file, or "" if no data.
        """
        import calendar
        today = date.today()
        year  = year  or today.year
        month = month or today.month

        month_str    = f"{year}_{month:02d}"
        summary_path = EARNINGS_DIR / f"summary_{month_str}.csv"
        month_prefix = f"{year}-{month:02d}"

        entries = [
            e for e in self.income["entries"]
            if e.get("date", "").startswith(month_prefix)
        ]
        if not entries:
            return ""

        by_platform = {}
        total_gross = 0.0
        total_net   = 0.0

        for e in entries:
            gross    = e.get("amount", 0.0)
            platform = e.get("platform", "Other")
            fee_rate = PLATFORM_FEES.get(platform, 0.0)
            net      = round(gross * (1 - fee_rate), 2)
            by_platform[platform] = by_platform.get(platform, 0.0) + gross
            total_gross += gross
            total_net   += net

        total_gross = round(total_gross, 2)
        total_net   = round(total_net,   2)

        EARNINGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([f"Hayeong Earnings Summary — {calendar.month_name[month]} {year}"])
            writer.writerow([])
            writer.writerow(["TOTALS"])
            writer.writerow(["Total Sales",       len(entries)])
            writer.writerow(["Gross Revenue",      f"${total_gross:.2f}"])
            writer.writerow(["Est. Net Revenue",   f"${total_net:.2f}"])
            writer.writerow([])
            writer.writerow(["BY PLATFORM", "Gross"])
            for platform, gross in sorted(by_platform.items()):
                writer.writerow([platform, f"${gross:.2f}"])
            writer.writerow([])
            goal = self.goal_status()
            writer.writerow(["WORKSTATION GOAL"])
            writer.writerow(["Goal",      f"${goal['goal']:.2f}"])
            writer.writerow(["Earned",    f"${goal['earned']:.2f}"])
            writer.writerow(["Remaining", f"${goal['remaining']:.2f}"])
            writer.writerow(["Progress",  f"{goal['percent']}%"])

        return str(summary_path)

    # ─────────────────────────────────────────
    # GOAL TRACKING
    # ─────────────────────────────────────────

    def goal_status(self) -> dict:
        earned    = self.income["total_earned"]
        remaining = max(0.0, WORKSTATION_GOAL - earned)
        percent   = min(100.0, (earned / WORKSTATION_GOAL) * 100)
        return {
            "goal":      WORKSTATION_GOAL,
            "earned":    earned,
            "remaining": remaining,
            "percent":   round(percent, 1),
        }

    def summary(self) -> str:
        """Human-readable status summary."""
        goal     = self.goal_status()
        pending  = len(self.get_pending_proposals())
        approved = len(self.get_approved_proposals())
        active   = len(self.products["active"])
        filled   = int(goal["percent"] / 5)
        bar      = "█" * filled + "░" * (20 - filled)

        return (
            f"Workstation Fund: ${goal['earned']:.2f} / ${goal['goal']:.2f}  "
            f"({goal['percent']}%)\n"
            f"[{bar}]\n"
            f"Proposals pending your review: {pending}\n"
            f"Approved / in progress: {approved}\n"
            f"Active listings: {active}"
        )


if __name__ == "__main__":
    mgr = IncomeManager()
    print(mgr.summary())
    p = mgr.submit_proposal(
        title="Test art pack",
        stream=STREAM_DIGITAL_ART,
        description="10-piece fantasy wallpaper pack for Gumroad",
        estimated_value=45.0,
        platform="Gumroad",
    )
    print(f"Proposal submitted: {p['id']}")
    mgr.approve_proposal(p["id"], "looks good, try it")
    print(f"Approved. Get approved: {mgr.get_approved_proposals()[0]['status']}")
    mgr.mark_executing(p["id"])
    mgr.mark_complete(p["id"], output_path="output/test_pack/", hayeong_note="10 images ready")
    mgr.mark_listed(p["id"], listing_url="https://gumroad.com/l/test", platform="Gumroad")
    entry = mgr.log_sale(p["id"], 15.00, platform="Gumroad")
    print(f"Sale logged: {entry['id']}, total: {mgr.income['total_earned']}")
    print(mgr.summary())
