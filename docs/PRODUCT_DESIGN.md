# Codex Pro Planning Bridge Product Design

## Overview

Codex Pro Planning Bridge is a plugin concept that separates software execution from high-level project planning.

## Core Idea

Use:

- Codex as implementation engineer.
- ChatGPT Pro as architecture planner.

## Architecture

```
User Request
    |
    v
Codex
    |
    v
Context Collector
    |
    v
REQUEST.md
    |
    v
ChatGPT Pro
    |
    v
PLAN.md
    |
    v
Codex Implementation
```

## Principles

1. No API dependency for planning.
2. No automated browser scraping.
3. Local-first context collection.
4. Human confirmation before Pro submission.

## MVP Components

- plugin manifest
- Codex skill
- context collector
- prompt builder
- ChatGPT handoff helper

## Future

- plan validation
- project memory
- architecture review loop
