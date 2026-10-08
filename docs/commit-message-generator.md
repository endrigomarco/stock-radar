# Commit message generator (on demand)

Use this guide only when explicitly referenced. It does not automatically change the format of every
commit or authorize any Git operation.

## Usage and evidence

Ask: `Generate the commit message using @docs/commit-message-generator.md`.

Inspect `git status --short`, `git diff` and `git diff --staged` before composing the message. Inspect
relevant untracked files separately, since ordinary diffs do not include them. Never read private
environment files or data dumps to generate a subject.

Describe the actual changes selected for the commit. When the user says to include everything, consider
all intended versionable changes, not just the latest conversation topic. Distinguish staged changes
from unstaged work and do not imply the generated command stages either. If the selected scope is
materially unclear, clarify it. If there are no changes, report that instead of inventing a message.

## Output format

Return one copyable command containing a single English subject, with no body, scope or footer:

```text
git commit -m "<type>: <imperative description>."
```

Generating this text never authorizes executing it. Choose wording that needs no shell interpolation;
do not include backticks, dollar signs or embedded quotation marks in the subject.

## Types

| Type | Purpose |
|---|---|
| `feat` | New functionality or changed application behavior |
| `fix` | Correction of an existing defect |
| `chore` | Documentation, tooling, configuration or other maintenance |

For a mixed change, choose the type that describes its principal outcome. Do not combine types.

## Wording

- Start with an imperative verb such as `add`, `fix`, `remove`, `preserve` or `simplify`.
- Use lowercase prose, preserving established capitalization for names such as Docker, PostgreSQL and MCP.
- End with a period and aim for a subject of at most 72 characters.
- State the concrete change. Avoid vague phrases such as `update things` or `improve the project`.
- Summarize the main outcome instead of listing every file or implementation detail.
- Omit paths, line numbers, ticket numbers, emojis and explanations of motivation.
- Never use em dashes.
- Do not claim deployment, live TradingView integration, Cowork connectivity or passing checks without
  corresponding evidence. Local synthetic tests do not establish live integration.

## Stock Radar examples

These illustrate the format and must not substitute for inspecting the current changes:

```text
git commit -m "feat: bootstrap the Stock Radar backend with REST and MCP."
git commit -m "feat: add idempotent webhook receipt and recovery."
git commit -m "fix: preserve the earliest trigger event on delayed delivery."
git commit -m "chore: document error tracking and log retention."
```

## Git boundaries

Follow [Git workflow](git-workflow.md). Do not stage files, create commits, push, tag or publish as part
of generating a message. Keep secrets, observations, logs and database dumps out of the proposed scope.
The user reviews and executes the command separately.
