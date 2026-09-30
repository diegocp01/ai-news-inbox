# Feature Launches and Education-Robot Pilots

## Official feature announcements mirrored across social networks

When an announcement is on a forbidden network such as X:

1. Search the exact opening sentence in quotes.
2. Look for an official cross-post from the same company on LinkedIn or another compliant host.
3. Fetch the cross-post HTML and extract `og:title`, `og:description`, and `og:image`.
4. Verify the image URL resolves directly to an image.
5. Prefer the exact official cross-post over a generic product page that does not mention the feature.

Example pattern: a Claude Cowork “Record a skill” announcement was mirrored on Claude’s official LinkedIn page. The LinkedIn description preserved the workflow, menu location, and eligible plans, while its feed image provided story-specific art.

Also check **product help centers** the same day: Anthropic often updates `support.claude.com` voice/tool docs in lockstep with social copy. When the help article states the new behavior (models in voice, mid-call connectors), prefer that durable URL over LinkedIn or a blank field.

### Inference-platform blogs on `.ai`

Vendor study posts on hosts like `fireworks.ai` cannot be final URLs. Prefer:

1. The company’s LinkedIn announcement that restates the benchmark numbers, or
2. Independent write-ups of the same study.

Do not “upgrade” a blocked blog URL to the company homepage—that loses the story anchor.

### Grok / SpaceXAI consumer availability pastes

“Available on grok.com, X, iOS, Android” pastes:

1. Skip `x.ai/news/...` (`.ai`).
2. Use TechCrunch, Reuters, Android Authority, or App Store listing as appropriate.
3. Attribute “most capable” as company positioning; include API $in/$out only when confirmed by press or a compliant surface.

## Embedded and isolated browser launches

For browsers embedded inside agent workspaces such as Cowork:

1. Distinguish the product surface precisely: an in-task side-panel browser is not a browser extension, the user’s ordinary browser, or a general browser product.
2. Verify whether the agent opens the browser automatically for website tasks, whether actions remain visible, and whether users can intervene or approve sensitive steps.
3. Check isolation claims separately: ordinary tabs, bookmarks, browsing history, cookies, and saved passwords may remain outside the workspace browser even when the agent can navigate and fill forms within its own session.
4. Separate browser automation from credential access. If a password manager or credential broker completes sign-in, state which component handles secrets and attribute “the model never sees the password” to the vendor unless independently established.
5. Verify MFA, CAPTCHA, payment, submission, and confirmation behavior rather than inferring fully autonomous completion from example tasks.
6. Do not use an earlier preview or reverse-engineered build article as the final URL for a later public launch. Require current launch confirmation; an older preview may supply a verified feature screenshot only.

If the strongest current publisher is blocked, recover its resolved canonical URL from the news redirect, but keep substantive claims limited to the current headline, accessible same-event reporting, and primary launch wording. Do not silently combine pre-launch article details with a launch claim unless the launch itself confirms them.

## Education robotics pilots

Treat “robot teacher” as headline shorthand until the deployment details are checked.

Verify:

- whether the system replaces an educator or assists one;
- pilot start date and whether deployment is confirmed or planned;
- grades and courses involved;
- whether the robot is stationary, mobile, autonomous, or teleoperated;
- whether the quoted price covers hardware alone or a package including software, avatars, support, or curriculum integration;
- privacy controls, internet connectivity, recording/facial-recognition status, and curriculum grounding when reported.

Newsletter framing should use “humanoid classroom assistant” or “pilot” when a human teacher remains responsible. If the hero image is a vendor-generated classroom rendering rather than a deployment photo, it is usable but should not be mistaken for evidence that the robot is already operating in class.
