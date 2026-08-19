# Codex Pro Planning Bridge

A bridge that lets Codex use ChatGPT Pro as a high-level architecture planning assistant.

## Vision

Codex is optimized for software implementation. ChatGPT Pro is used as the planning architect for complex engineering decisions.

The workflow:

```
Codex
  -> collect repository context
  -> generate planning request
  -> ChatGPT Pro architecture review
  -> save PLAN.md
  -> Codex implementation
```

## Goals

- Avoid API-based planning costs.
- Keep planning quality from ChatGPT Pro.
- Let Codex focus on repository analysis and implementation.
- Keep sensitive project data local by default.

## Status

Project is in design/MVP stage.

## Roadmap

- [x] Product design
- [ ] Plugin manifest
- [ ] Codex skill
- [ ] Context collector
- [ ] Prompt generator
- [ ] Plan validator

## License

MIT
