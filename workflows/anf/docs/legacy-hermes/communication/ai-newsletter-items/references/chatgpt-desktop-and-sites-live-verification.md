# ChatGPT desktop and Sites: live verification notes

Use this reference for same-day claims about ChatGPT Work, Codex in the desktop app, plugins, shared threads, and Sites collaboration.

## Authoritative discovery path

1. Inspect `https://learn.chatgpt.com/docs/changelog` for the dated launch entry.
2. Follow the feature-specific documentation link from that entry; do not rely on social copy alone.
3. If the accessibility snapshot omits bold labels or menu names, inspect the containing changelog item’s `innerText` and `innerHTML`. The docs sometimes place essential feature names and settings inside `<strong>` elements that snapshots render as blank.
4. Separate product surface, host app, operating system, plan gate, workspace gate, and rollout wording.
5. Apply ANF URL policy at the end. `learn.chatgpt.com` is verification evidence but cannot be the final `URL:` under the current policy. Its direct OpenGraph image may still be used if it passes the separate image policy.

## Shared Codex thread snapshots

The August 20, 2026 changelog documents **read-only snapshots of local Codex threads**, not blanket sharing for every ChatGPT Work conversation.

- Surface: ChatGPT desktop app for macOS.
- Eligibility: all Codex plans.
- Snapshot behavior: static; later changes to the original thread do not update it.
- Personal-account links: anyone with the link can open them.
- Workspace-account links: restricted to members of the originating workspace.
- Safety: known secret patterns are redacted, but sensitive content can remain; users should review before sharing.
- Management: links can be viewed or revoked in ChatGPT Data Controls under Shared links.

Do not broaden this into web, mobile, Windows, CLI, IDE, live collaboration, or all Work chats unless current documentation explicitly does so.

## Apple Messages plugin

The plugin documentation establishes:

- It can read/search iMessage, SMS, and RCS chats on the Mac and send through Apple Messages.
- It works in ChatGPT Work and Codex inside the ChatGPT macOS desktop app.
- It is available on all plans but, for the documented release, only in the Apple Silicon (`arm64`) build.
- It does not work in regular ChatGPT chats, web/mobile, Codex CLI, or the IDE extension.
- Sends require approval by default. Persistent approval removes the final per-send review and should be described as a risk, not merely convenience.
- Managed-workspace administrators can disable it through Computer Use controls.

## ChatGPT Sites co-editing

Treat availability as conditional (`where available`) and collaboration as workspace-scoped.

- Owners can invite active members of the same workspace as editors.
- Editors can modify a Site, save versions, and publish updates only after the owner performs the first publish.
- Editors can read live database data; note this material access consequence.
- Owners retain audience, access, settings, analytics, version restoration, and ownership controls.
- Editors cannot invite/remove collaborators, change audience, manage settings/analytics, restore versions, transfer ownership, or perform the first publish.

Do not repeat social shorthand that Codex “handles git management and CI behind the scenes” unless the current docs establish those exact mechanics. The docs verify that local builds can be associated with a Git commit; that alone does not prove a general CI workflow.
