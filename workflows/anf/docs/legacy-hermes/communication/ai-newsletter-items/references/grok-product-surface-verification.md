# Grok product-surface verification for ANF items

Use this note when an intake says “Grok,” “Grok Bot,” “connector,” “plugin,” or “Microsoft integration.” These names cover distinct products and capability sets.

## Separate the surfaces

1. **Grok at grok.com/mobile:** Uses xAI connectors configured at `grok.com/connectors`. Outlook Mail, Outlook Calendar, OneDrive, Teams, and SharePoint documentation here does not automatically describe Grok Bot.
2. **Grok Bot:** Uses the Cursor-backed plugin/MCP marketplace under Settings → Plugins. Verify its capabilities from the live Cursor Marketplace and the `cursor/plugins` repository.
3. **Standalone Microsoft 365 add-ins:** Grok for Outlook, Word, Excel, and PowerPoint is installed from Microsoft Marketplace and runs as its own add-in inside those Office applications. Marketplace/add-in behavior must not be generalized to Grok Bot, grok.com connectors, or Microsoft Copilot.
4. **Microsoft 365 Copilot model choice:** Grok can appear as a selectable model inside Copilot experiences in Word, Excel, or PowerPoint. Verify the named apps, web/desktop surfaces, preview or GA status, eligible program, administrator opt-in, excluded regions, and whether the model is hosted outside Microsoft-managed environments.
5. **Copilot Studio external models:** This is a maker/admin surface for building agents. Its model list and safety notices do not prove that Grok is selectable in end-user Microsoft 365 Copilot apps.
6. **Microsoft Foundry models:** Azure deployment availability proves an API/model-catalog surface, not Office or Copilot availability.
7. **GitHub Copilot:** Model availability in IDEs, CLI, or coding agents is separate from Microsoft 365 Copilot despite the shared “Copilot” name.
8. **Grok Build/API:** Treat these as separate surfaces again; do not inherit consumer, Bot, Microsoft, or GitHub integrations without direct evidence.

## Verification workflow

- Search the exact visible announcement phrase first and classify the product surface before opening adjacent documentation.
- For a standalone Office add-in, inspect the current Microsoft Marketplace listing. For Microsoft 365 Copilot model choice, inspect same-event coverage plus live Microsoft Learn pages for external-model connection, administrator controls, processing location, safety warnings, preview status, and geography; do not substitute a Marketplace listing.
- For a newly added Cursor-backed plugin, inspect the merged PR, plugin manifest/README, live Marketplace description, minimum client version, and current availability.
- Prefer a merged official repository PR or live Cursor Marketplace page as the compliant final URL when an xAI announcement is on a blocked `.ai` or social host.
- Use the repository PR’s combined product-art image when it directly represents several plugins; verify that it resolves as an image. A single-plugin Marketplace OpenGraph card is the fallback.
- State capabilities per service, not as one blanket “read, write, and act” claim.

## Microsoft plugin capability example

For the August 2026 Cursor plugin set:

- **Outlook:** search, read, and send Microsoft Outlook email; look up contacts.
- **Outlook Calendar:** list, create, update, and cancel events.
- **OneDrive:** browse, search, and read files.

Therefore, wording such as “write across Microsoft accounts” overstates the OneDrive plugin. Correct the newsletter summary explicitly when the unsupported write claim is central.

## Pitfalls

- Do not cite grok.com connector docs as proof of Grok Bot plugin behavior.
- Do not cite an Office add-in listing as proof that Grok Bot can perform the same actions.
- Do not cite Copilot Studio or Microsoft Foundry availability as proof that Grok is selectable in Word, Excel, PowerPoint, Teams, Outlook, or consumer Copilot.
- Preserve focused-release and preview boundaries: a rollout to eligible Frontier organizations is not general availability, and later expansion plans are not shipped surfaces.
- When Microsoft says an external model processes data outside Microsoft-managed environments, do not imply that Microsoft product terms, data-residency commitments, audit controls, or copyright commitments automatically apply; summarize the material boundary when space permits.
- Do not infer file upload, editing, deletion, event triggers, multi-account routing, or shared-drive access from broad phrases like “act across your Microsoft account.”
- An older forum post saying a plugin did not exist may have been true before a marketplace merge. Check current repository and Marketplace state before repeating it.
