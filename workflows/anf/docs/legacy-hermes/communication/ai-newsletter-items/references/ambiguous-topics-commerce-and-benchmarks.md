# Ambiguous topics, agentic commerce, and benchmark intakes

Use these patterns for terse ANF prompts where the product name, risk model, or evaluation claim needs disambiguation.

## Bare names and likely misspellings

- Search the exact term first across current news and ordinary web results.
- If results point only to unrelated people, places, or consumer brands, do not manufacture an AI connection.
- Ask one short clarification requesting a link, screenshot, description, or spelling check. If a plausible nearby name exists, offer it as a tentative candidate rather than assuming it.
- When the user confirms the candidate tersely (including a one-letter “y”), continue with the confirmed name, research it, and silently normalize the title.
- Correct category shorthand as part of the item. Example: an Arch Linux/Hyprland distribution is not a wholly new operating-system kernel; call it a Linux distribution while preserving the AI-news value.

## Agentic shopping and payment connectors

- Identify the payment product precisely (wallet, accelerated checkout, card vault, merchant network, or payment processor) and attribute unverified capability claims to the announcing company.
- Verify whether the agent can only discover products and prepare checkout, or can actually submit a purchase.
- Check supported merchants, geography, plans, confirmation requirements, spending limits, approval controls, refunds/returns, credential visibility, and rollout status.
- Do not infer safeguards that the announcement does not state. If material controls are unspecified, say so concisely rather than implying unrestricted autonomy or guaranteed safety.
- For social-only launches on forbidden hosts, leave `URL:` blank and use verified compliant product art.

## Conversational-AI benchmarks

- Report what is being measured (for example, end-of-turn or interruption detection), the corpus size and language, evaluation tracks, and the principal metrics.
- Distinguish recall, false-positive rate, and latency; a system can lead on recall while remaining too slow or trigger-happy for natural interaction.
- Prefer the benchmark’s own table and protocol over a marketing summary. State the strongest trade-off finding rather than declaring an overall winner when no system leads across all dimensions.
- Include material scope limits such as studio-recorded speech, dyadic conversations, one language, or incomplete evaluation of full-duplex models.

## Research-paper screenshots and image fallback

- Transcribe the visible title/author first, then resolve the exact paper with the arXiv Atom API when needed.
- Read the abstract and label conceptual papers as conceptual; do not turn an argument or framework into an empirical result.
- Prefer a directly relevant HTML figure and caption. If the paper has no HTML conversion or usable figure, use the paper page’s verified OpenGraph image (often the arXiv logo) rather than leaving `Image URL:` empty; the persistent ANF queue rejects empty image URLs.
