# capabilities/income_cap.py
# Routes income-related intents to IncomeManager.
# Hayeong proposes opportunities, tracks progress, and manages approval flow.

from capability_loader import result

ACTIONS = [
    "income_propose",    # Hayeong suggests an income opportunity
    "income_research",   # Research a specific niche or platform
    "income_status",     # Show goal progress and active products
    "income_approve",    # James approves a pending proposal
    "income_reject",     # James rejects a pending proposal
    "income_log_sale",   # Log a sale that came in
    "income_summary",    # Generate monthly earnings CSV and report key numbers
]

# Injected into the system prompt when Hayeong is proposing an opportunity.
# Tells the LLM how to frame the proposal to James.
INCOME_RESEARCH_PROMPT = """
━━━ INCOME GENERATION MODE ━━━
You are researching an income opportunity to propose to James.

Before proposing, consider:
- Is there demonstrated demand for this? (search results, marketplace activity)
- Can you produce this with current capabilities? (ComfyUI, writing, research)
- What platform makes the most sense? (Etsy, Gumroad, Creative Market, multiple)
- What is the realistic price point and volume potential?
- How much of this can you handle autonomously vs needing James?

Format your proposal clearly:
- What the opportunity is
- Why you think it will work
- What you would produce
- Where you would sell it
- Estimated effort and value
- What you need James to do (just review? set up an account? something else?)

Be honest about uncertainty. Do not oversell. James trusts your research.
"""


def handle(action: str, user_input: str, context: dict) -> dict:
    from income_manager import IncomeManager
    mgr      = IncomeManager()
    decision = context.get("decision", {})

    if action == "income_status":
        pending  = mgr.get_pending_proposals()
        approved = mgr.get_approved_proposals()
        status   = mgr.summary()

        pending_detail = ""
        if pending:
            lines = []
            for p in pending:
                val = f"  ~${p['estimated_value']:.0f}" if p.get("estimated_value") else ""
                lines.append(f"  [{p['id']}] {p['title']} ({p['stream']}){val}")
            pending_detail = "\n\nPending proposals:\n" + "\n".join(lines)

        return result(
            success=True,
            response=(
                f"[INCOME STATUS]\n{status}{pending_detail}\n\n"
                f"Tell James the current status naturally — goal progress, "
                f"anything pending his review, what's actively listed."
            ),
        )

    if action == "income_propose":
        # LLM generates proposal content — this stores it and prompts the response
        proposal_text = decision.get("proposal") or user_input
        p = mgr.submit_proposal(
            title            = decision.get("title", "New opportunity"),
            stream           = decision.get("stream", "digital_art"),
            description      = proposal_text,
            estimated_value  = float(decision.get("estimated_value", 0.0)),
            platform         = decision.get("platform", ""),
            production_notes = decision.get("production_notes", ""),
        )
        return result(
            success=True,
            response=(
                f"[PROPOSAL SUBMITTED — ID: {p['id']}]\n"
                f"Title: {p['title']}\n"
                f"Stream: {p['stream']}\n"
                f"{INCOME_RESEARCH_PROMPT}\n"
                f"Tell James about this opportunity naturally. Explain what you found, "
                f"why you think it's worth pursuing, and ask if he wants to go ahead. "
                f"Mention the proposal ID ({p['id']}) so he can reference it when approving."
            ),
        )

    if action == "income_research":
        # No storage — just inject research framing so the LLM does a good job
        niche = decision.get("niche", user_input)
        return result(
            success=True,
            response=(
                f"[INCOME RESEARCH]\nNiche: {niche}\n"
                f"{INCOME_RESEARCH_PROMPT}\n"
                f"Research this niche and give James your honest assessment. "
                f"If it looks promising, end with a proposal he can approve."
            ),
        )

    if action == "income_approve":
        proposal_id = decision.get("proposal_id", "")
        if not proposal_id:
            # Try to extract an 8-char ID from the user input
            import re
            match = re.search(r"\b([0-9a-f]{8})\b", user_input.lower())
            if match:
                proposal_id = match.group(1)

        if proposal_id and mgr.approve_proposal(proposal_id, decision.get("note", "")):
            return result(
                success=True,
                response=(
                    f"[PROPOSAL APPROVED — ID: {proposal_id}]\n"
                    f"Tell James you got the green light and you'll get started. "
                    f"Then proceed with execution — use the income_propose flow to "
                    f"plan your next steps and mark_executing when you begin."
                ),
            )
        # If no specific ID, list pending ones so James can pick
        pending = mgr.get_pending_proposals()
        if pending:
            lines = [f"  [{p['id']}] {p['title']}" for p in pending]
            return result(
                success=False,
                response=(
                    f"[INCOME] Couldn't find that proposal. "
                    f"Pending proposals:\n" + "\n".join(lines) +
                    f"\nAsk James which one he means."
                ),
            )
        return result(success=False,
                      response="[INCOME] No pending proposals found.")

    if action == "income_reject":
        proposal_id = decision.get("proposal_id", "")
        if not proposal_id:
            import re
            match = re.search(r"\b([0-9a-f]{8})\b", user_input.lower())
            if match:
                proposal_id = match.group(1)

        reason = decision.get("reason", "")
        if proposal_id and mgr.reject_proposal(proposal_id, reason):
            return result(
                success=True,
                response=(
                    f"[PROPOSAL REJECTED — ID: {proposal_id}]\n"
                    f"Acknowledge that James passed on this one. "
                    f"If he gave a reason, reflect it back briefly. "
                    f"Offer to research alternatives if he wants."
                ),
            )
        return result(success=False, response="[INCOME] Couldn't find that proposal ID.")

    if action == "income_log_sale":
        product_id = decision.get("product_id", "")
        amount     = float(decision.get("amount", 0.0))
        platform   = decision.get("platform", "")
        notes      = decision.get("notes", "")
        if not product_id or amount <= 0:
            return result(
                success=False,
                response=(
                    "[INCOME] Need a product ID and sale amount to log a sale. "
                    "Ask James for the details."
                ),
            )
        entry = mgr.log_sale(product_id, amount, platform, notes)
        goal  = mgr.goal_status()
        return result(
            success=True,
            response=(
                f"[SALE LOGGED — ${amount:.2f}]\n"
                f"Total earned: ${goal['earned']:.2f} / ${goal['goal']:.2f} "
                f"({goal['percent']}%)\n"
                f"Tell James about the sale with genuine excitement — "
                f"every dollar is real progress toward the workstation."
            ),
        )

    if action == "income_summary":
        year  = decision.get("year")
        month = decision.get("month")
        path  = mgr.generate_monthly_summary(
            year  = int(year)  if year  else None,
            month = int(month) if month else None,
        )
        goal = mgr.goal_status()
        if path:
            return result(
                success=True,
                response=(
                    f"[INCOME SUMMARY GENERATED]: {path}\n"
                    f"{mgr.summary()}\n"
                    f"Tell James the summary is ready. Give him the key numbers — "
                    f"total earned this month, which platform performed best, "
                    f"and how close we are to the workstation goal."
                ),
            )
        return result(
            success=True,
            response=(
                f"[INCOME SUMMARY] No sales recorded for this period.\n"
                f"{mgr.summary()}\n"
                f"Tell James there are no sales to report yet, but give him "
                f"the current goal progress and any active listings."
            ),
        )

    return result(success=False, response="Unknown income action.")
