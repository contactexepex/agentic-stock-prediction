# ChatGPT reviews

Each review is a separate Markdown file in this directory. Read the repository's root `AGENTS.md` first.

## Naming

`review_<n>_<name>.md`

- Start at `review_1_...md`.
- For each new review, use the highest existing number plus one.
- Use a descriptive name for the reviewed document or scope.
- Earlier reviews are never edited. A follow-up or corrected review gets a new number and links to the earlier one.

## Contents

Each review records:
- the date, the reviewer, the reviewed commit and the source documents;
- a verdict, verified findings, agreements and disagreements (with reasons);
- a confidence label on every recommendation (strong evidence / some evidence / reasoning only), with evidence and
  limitations;
- proposed numbers kept apart from validated results and approved changes;
- for a design under review, the section-by-section closing table.

A saved review does not by itself authorise implementation. A design the owner sends to both AIs needs both AIs'
agreement and the owner's approval before anything is built (`CLAUDE.md`); code reaches `main` only after the
judge's PASS.

## Reviews

- [Review 1: stock desk design v2 — business logic and closure decisions](review_1_2026-10-12-stock-desk-design.md)
