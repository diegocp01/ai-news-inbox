# World-model and spatial-generation launch verification

Use this for announcements that combine image/video generation, 3D reconstruction, simulation, or robotics under the label “world model.”

## Scope distinctions

- Classify the demonstrated system as one or more of: **renderer** (predicts views/pixels), **reconstructor** (recovers explicit geometry), **simulator** (predicts state evolution or sensor observations), or **planner/controller** (chooses actions). Do not imply all four from the phrase “world model.”
- Separate accepted modalities from generated outputs. “Omni” may mean one architecture handles text, images, camera poses, depth, video sequences, and 3D outputs; it does not establish support for audio, actions, forces, tactile signals, meshes, or robot control unless documented.
- Distinguish generated novel views and hallucinated completion of unseen regions from measured reconstruction or a faithful digital twin.
- For robotics, separate Real-to-Sim scene/sensor generation from physics simulation, policy training, policy evaluation, and direct robot planning.

## Claims to verify

- Architecture and whether the model was pretrained from scratch or assembled from specialists.
- Native camera geometry versus camera motion described only through text prompts.
- Maximum duration, resolution, number of reference images, and whether those limits appear in a curated demo or a generally available product.
- Explicit 3D formats such as point clouds, depth maps, meshes, or Gaussian splats.
- Benchmark provenance: company-run versus independent; reproduced baselines; native inputs given to the new model versus weaker text approximations given to competitors; third-party raters versus third-party reproduction.
- Access state: waitlist, selected-partner early access, public API, downloadable weights, or shipping product integration.
- Missing launch artifacts that materially limit evaluation: public model ID, API pricing, latency, model card, paper, code, training-data disclosure, or named partners.

## Writing guidance

- Prefer “introduced” or “unveiled” for early access; do not say “released” or “launched publicly” without public availability.
- Attribute benchmark superiority and “pixel-perfect” language to the company unless independently reproduced.
- A concise summary should state the strongest demonstrated capabilities, the access state, and one material evidence limitation when relevant.
- If the primary announcement is on a policy-blocked `.ai` host, use exact same-event independent coverage as the final URL. The primary page may still be used for technical verification, and a compliant story-specific image from the chosen coverage may be used.

## Pasted-email intake pattern

For launch emails without a visible URL, search one distinctive sentence in quotation marks plus the company/product name. Resolve the primary announcement first, then seek exact same-event compliant coverage if policy blocks the official host. Do not use an older adjacent product page merely because it describes the same company or technology.