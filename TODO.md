# TODO — TEB AI Hackathon Submission

Deadline: **Sunday 25 October 2026, 11:30 sharp**

## Critical Path

- [ ] **Clarify AI usage angle** — The hackathon is an AI hackathon. Submission requires explaining "How AI is used". Our deliverable is an interoperability profile. Options to define:
  - AI-assisted design process (Claude as co-author)
  - AI in the HEMS for local optimization / SoC prediction / flex capacity forecasting
  - AI at aggregator level for aggregated response prediction / grid state forecasting
  - Needs a clear, honest answer — judges will probe this

- [ ] **Create or decide on demo** — Submission asks for a live URL or 5-min video walkthrough. Options:
  - Spin up MQTT broker + simulated flex-request/response flow (small Python/Node script)
  - Architecture walkthrough video (screen recording of the profile docs)
  - State clearly that it's a design deliverable, not running code
  - "Working demo > polished slides" per template

- [ ] **Push repo to GitHub** — Jury needs access. Create remote, push, share with TEB organisers.

## Submission Form (Sections 1–7)

Submission is via TEB form at [submission link]. Template in `challenge/TEB-AI-Hackathon-Submission-Template.docx.md`.

- [ ] **Section 1 — Project basics**
  - [ ] Project title (short, memorable noun)
  - [ ] One-line pitch

- [ ] **Section 2 — Team**
  - [ ] Team name
  - [ ] Team members (name, org, GitHub handle, role) — needs Jürgen's input
  - [ ] Primary contact email

- [ ] **Section 3 — Challenge track**
  - Track: Grid-Friendly / Grid-Serving Storage
  - Challenge partner: Smart Grids Austria (Christoph Wanzenböck)

- [ ] **Section 4 — What you built** (content exists in `profile/`, needs condensing)
  - [ ] Problem you solved (2–3 sentences)
  - [ ] Solution overview (1 paragraph)
  - [ ] How AI is used (2–3 sentences) — depends on AI angle decision above
  - [ ] Security and resilience (2–3 sentences)
  - [ ] Data and environments + confirmation no live infra tested
  - [ ] Tech stack (MQTT v5, OpenADR 2.0b, JSON, TLS, Python/Node if demo built)

- [ ] **Section 5 — Links**
  - [ ] Code repository URL (after GitHub push)
  - [ ] Demo link (after demo decision)
  - [ ] Documentation link (README.md)
  - [ ] Pitch deck (optional)
  - [ ] Other links (poster PDF, profile docs)

- [ ] **Section 6 — Notes for the jury**
  - This is an interoperability profile design, not running production code
  - Aligned with Smart Grids Austria system architecture for flexible assets
  - Dual-protocol: OpenADR 2.0b (device) + MQTT v5 (backend)
  - Validated approach with challenge partner (Wanzenböck conversation)

- [ ] **Section 7 — Follow-up checkboxes** — needs Jürgen's preference
  - [ ] TEB Klub invitation?
  - [ ] Contact permission?
  - [ ] Photo/project sharing permission?

## Done

- [x] Challenge problem statement documented
- [x] Smart Grids Austria poster downloaded, converted to markdown
- [x] Architecture corrected: aggregator-centric (not DSO-direct)
- [x] Dual-protocol design: MQTT (backend ↔ aggregator) + OpenADR (device ↔ backend)
- [x] Full IES profile drafted (6 files in `profile/`)
- [x] Open questions documented
- [x] Submission template added to repo
- [x] README references verified
