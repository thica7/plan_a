# ADR-0003: L1/L2/L3 Competitive Model

Status: Accepted

## Context

Enterprise competitive intelligence needs to distinguish direct product
battlecards, adjacent workflow comparisons, and broad market landscapes.

## Decision

Use `L1`, `L2`, and `L3` as the core competitor-layer model:

- `L1`: direct product competitor
- `L2`: adjacent workflow or platform alternative
- `L3`: market landscape/category scan

## Consequences

Scenario packs, QA rules, readiness scoring, and evidence gaps are layer-aware.
The model is intentionally simpler than a research-grade knowledge graph.
