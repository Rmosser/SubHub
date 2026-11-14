# Documentation Index

This is the Context Map for SubHub. Start here, then load only the documents needed for the current question.

## Product and boundaries

- Product overview, access behavior, language behavior, local start, and deployment entry points: `README.md`
- Authoritative product configuration principles and development-role boundary: `docs/design-docs/core-beliefs.md`
- Cross-cutting product/design principles: `docs/golden-principles.md`
- Frontend design system and shell guidance: `DESIGN.md`
- Proxy client settings UI inventory, measured tokens and pixel replicas (Surge iOS, Shadowrocket, Clash Mi) for the 配置与场景 page: `design/client-ui-replica/README.md`
- Glass workbench prototype (final) that the frontend shell is ported from: `design/glass-workbench/FINAL.md`

## Architecture and domain behavior

- System boundaries, modules, and data flow: `docs/architecture/system-overview.md`
- Derived configuration intent, compatibility projections, diagnostics, and evidence inventory: `docs/design-docs/configuration-intent.md`
- Generated field-by-field intent inventory: `docs/design-docs/intent-inventory.md`
- Product design notes and domain decisions: `docs/design-docs/`

## API and subscription contracts

- HTTP routes and payload contract: `docs/api/http-api.md`
- Subscription rendering/output semantics: `docs/api/subscription-output-contract.md`

Maintenance rule: HTTP surface changes synchronize `docs/api/http-api.md`; subscription output semantic changes synchronize `docs/api/subscription-output-contract.md`.

## Quality and executable feedback

- Test, lint, build, docs audit, smoke, setup, and runtime readback commands: `docs/quality.md`
- Path-to-document synchronization rules used by the docs audit: `docs/doc-sync-rules.json`
- UI smoke task: `docs/operations/ui-smoke-test-task.md`

## Local development and operations

- Clash Mi import, override and update behavior: `docs/operations/clash-mi-import.md`
- Local development: `docs/operations/local-dev-runbook.md`
- Runtime operations: `docs/operations/runbook.md`
- Troubleshooting: `docs/operations/troubleshooting.md`
- Secret rotation: `docs/operations/secret-rotation.md`
- LazyCat egress bridge: `docs/operations/lazycat-egress-bridge.md`

## Deployment and release

- LazyCat build/install/runtime deployment: `docs/deployment/lazycat-deployment.md`
- Product release checklist: `docs/governance/release-checklist.md`
- Repository branch and commit conventions: `docs/governance/git-workflow.md`
- Contributor workflow: `CONTRIBUTING.md`

Maintenance rule: deployment/runtime configuration changes synchronize `docs/deployment/lazycat-deployment.md`.

## Optional planning

- Optional complex-task / Codex Plan template: `docs/plans/template.md`
- Agent configuration roadmap and stage status: `docs/plans/agent-configuration.md`

Plans are aids, not repository gates. No task requires an Active Plan merely because it is non-trivial.

