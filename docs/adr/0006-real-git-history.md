# ADR-0006: Real Git History

Status: Accepted

## Context

The plan explicitly rejects fabricated timestamps, imported fake history, or
claims about development events that did not happen in this repository.

## Decision

Keep real commits only. Do not rewrite commit dates to simulate earlier work.

## Consequences

Progress is represented by actual commits and verifiable tests. Review artifacts
may remain untracked unless they are intentionally part of implementation.
