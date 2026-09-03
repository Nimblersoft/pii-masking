---
title: "PII Masking Documentation Blueprint"
type: concept
status: active
confidence: strong
tags:
  - documentation
  - meta
last_checked: 2026-09-03
---

# PII Masking — Documentation Blueprint

This document defines how documentation is organized in this repository: the
divide between versioned and unversioned material, the directory layout, the
filing rules that keep folders from overlapping, and the frontmatter every
document carries.

---

## 1. The Clean Divide: Versioned Wiki vs. Scratch Space

Two environments, deliberately separated:

| | **Versioned wiki** (`docs/`) | **Scratch space** (unversioned) |
|---|---|---|
| **Contains** | Invariants, contracts, decisions, runbooks | Raw notes, meeting transcripts, clippings, work-in-progress drafts, full research dumps |
| **Trust** | High — reviewed, current, safe to act on | Low — unreviewed, possibly stale or contradictory |
| **Lifecycle** | Git-tracked, reviewed, diffable | Freely edited, never reviewed, disposable |
| **Audience** | Humans + agents, as source of truth | Humans thinking out loud; agents reading for *input* only |

**Rules:**

1. **The repository is the SSOT.** `docs/` is the single source of truth for
   architecture, decisions, contracts, and procedures. Nothing outside it is
   authoritative.
2. **Scratch is input, never output.** An agent may *read* the scratch space
   to synthesize a document, but the synthesized result is committed to
   `docs/` — the scratch original is not the deliverable and is never linked
   as the canonical reference.
3. **No shared write surface.** Do not mount or sync the scratch space into
   the repository working tree. Read it over its own interface, synthesize,
   then commit.
4. **Cite, don't inline.** When a `docs/` file distills something large, it
   states the takeaway and links back to the full source rather than pasting
   it in.

> **This project's scratch space:** the shared SilverBullet space
> (`silverbullet` skill / instance), used for raw notes, transcripts, and full
> research dumps. Local throwaway experiments go in a gitignored `scratch/`
> directory if ever needed.

---

## 2. Organization System

A **hybrid folder/tag structure**:

* **Folders for namespacing** — physical directories isolate document
  *kinds*. This scopes search paths and prevents naming collisions.
* **Tags for typing** — YAML frontmatter classifies the document type (adr,
  spec, runbook) and cross-cutting concerns, so views can be compiled across
  folders without reorganizing them.

---

## 3. Directory Layout

```
pii-masking/
├── AGENTS.md                        # Core agent operational context (SSOT)
├── CLAUDE.md                        # Thin pointer to AGENTS.md
├── CONTEXT.md                       # Domain glossary
├── README.md                        # Human-facing overview
└── docs/
    ├── index.md                     # Wiki landing page / document map
    ├── docs-organization-blueprint.md  # This file
    ├── adr/                         # Architectural Decision Records (the why)
    ├── specs/                       # Module contracts (the what)
    ├── architecture/                # System designs, topologies, threat models
    ├── runbooks/                    # Exact command recipes (the how)
    ├── processes/                   # Standing policies, governance, boundaries
    ├── workflows/                   # Lifecycle flows spanning multiple systems
    └── research/                    # Takeaways and reports (full sources in scratch)
```

Folders earn their first real file. `adr/`, `specs/`, and `runbooks/` exist
today; create `processes/`, `workflows/`, or `research/` only when a document
actually arrives for them.

### Bounded Categorization Rules (Filing Best Practices)

**When two folders could plausibly hold a document, this table decides.**

| Location | Target | Audience / Use | Primary Question Answered |
| :--- | :--- | :--- | :--- |
| **`/skills/`** *(user-level)* | Executable agent logic | **Agent-harness only.** Parsed natively as direct capability prompts. | *What capabilities does the agent possess?* |
| **`docs/adr/`** | Decision Records | **Human + Agent.** Choices that are hard to reverse, surprising without context, and the result of a real trade-off. | *Why is it built this way?* |
| **`docs/specs/`** | Module & Feature Contracts | **Human + Agent.** Behavioral contract per module — one spec per code module (ADR 0007). | *What must this module do?* |
| **`docs/architecture/`** | Structural Designs | **Human + Agent.** Topologies, component maps, threat models, C4 diagrams. | *What is wired to what?* |
| **`docs/processes/`** | Standing Policies & Guidelines | **Human + Agent.** Rules, governance, and write discipline. | *What are the rules and boundaries of this system?* |
| **`docs/workflows/`** | Lifecycle Pathways | **Human + Agent.** Coordination sequences and pipeline lifecycles across systems. | *How does work flow from start to completion?* |
| **`docs/runbooks/`** | Technical Action Recipes | **Human (or authorized agent).** Exact CLI checklists for setup, deployment, or troubleshooting. | *What is the exact sequence of commands?* |
| **`docs/research/`** | Research Takeaways | **Human + Agent.** Summarized findings and recommendations. Full documents stay in the scratch space. | *What did we learn, and what do we recommend?* |

Two tie-breakers worth stating explicitly:

* **ADR vs. spec** — an ADR records a *choice between alternatives* and freezes
  at the moment of decision; a spec records the *current required behavior*
  and is updated whenever behavior changes. If it would need editing after a
  code change, it is a spec.
* **Workflow vs. runbook** — a workflow explains the *path and its
  transitions*; a runbook gives the *commands*. If a reader could copy-paste
  it, it is a runbook.

---

## 4. Metadata Schema & Frontmatter Conventions

Every document carries standard YAML frontmatter so parsers and query tooling
can filter it.

### A. Project / Concept Document

```yaml
---
title: "Authentication Subsystem"
type: concept | entity | index
status: active | review-needed | stale
confidence: strong | moderate | weak
sources:
  - "<link to the scratch-space original this was synthesized from>"
tags:
  - security
last_checked: <YYYY-MM-DD>
---
```

### B. Decision Record (ADR)

```yaml
---
title: "ADR-0001: <Decision>"
type: adr
status: proposed | accepted | superseded
decided_by: <name>
date: <YYYY-MM-DD>
supersedes: "docs/adr/<nnnn>-<slug>.md"   # omit if none
---
```

### C. Spec

```yaml
---
title: "Spec: <module>"
type: spec
status: active | superseded
covers: <source path this spec governs>
last_checked: <YYYY-MM-DD>
---
```

`status` and `last_checked` are what make staleness detectable — a spec that
no longer matches the code should be marked `stale` rather than silently left
to mislead.

Each code module governed by a spec carries a matching pointer at the very
top of the file (`# Spec: docs/specs/<name>.md`) so the link is bidirectional.

---

## 5. Compiled Views

> **View compiler:** none — `docs/index.md` is hand-maintained.
