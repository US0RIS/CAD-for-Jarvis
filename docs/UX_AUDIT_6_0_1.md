# ForgeCAD 6.0.1 — UX Audit and Revision Record

**Branch:** `forgecad/6.0.1`  
**Scope:** complete desktop interaction audit over the validated ForgeCAD 6.0 engineering substrate  
**Release principle:** 6.0.1 may improve discoverability, interaction correctness, information architecture, and desktop ergonomics without weakening canonical engineering-state or evidence boundaries.

## UX standard

ForgeCAD is not being evaluated as a generic CAD skin. The release succeeds when the desktop makes the AI-native physical-engineering model legible and controllable: the user can move from intent to geometry, real components, code, analysis, branches, manufacturing, and physical-world state without discovering that a capability exists only in an API or orphaned component.

The audit therefore treats the following as release-level defects, not cosmetic issues:

1. A canonical capability exists but has no reachable desktop workflow.
2. An interaction can silently operate on the wrong branch/object/revision.
3. A UI label implies physical truth that the evidence model does not establish.
4. A primary work surface is technically present but too constrained to perform its task.
5. Renderer/engine transport prevents an exposed control from completing its mutation.
6. Failure/offline/busy state destroys user input or makes the active operation ambiguous.

## Findings and revisions

| Severity | Finding | User impact | 6.0.1 revision | Verification |
|---|---|---|---|---|
| P0 | Design-lineage engine APIs and a design inspector existed, but the active shell exposed only branch switching. | Users could not create a safe experimental branch, mark known-good/failed variants, or compare a failed design against a working design from the main UI. | Added a first-class Design Lineage panel in Properties plus a **Manage** affordance beside BRANCHES. It exposes branch creation, working/not-working/unverified labels, physical-evidence state, and canonical comparison. | `e2e/design-lineage-ux.spec.ts` |
| P0 | Branch labels could be read as equivalent to real-world validation. | A user could mistake “working” for physical verification. | Design Lineage explicitly states that status is a design label and that physical verification only comes from revision-bound recorded evidence. Existing `physical_verified` state remains independently displayed and is never synthesized by the UI. | Lineage UX regression + canonical API assertions |
| P1 | Parametric feature-history editing was implemented but orphaned from the shell. | Fabricated CAD bodies appeared substantially less editable than the engine actually supports. | Fabricated/imported objects now expose **PARAMETRIC CAD** directly in Object Properties with the existing Feature History editor: add, edit, suppress, duplicate, reorder, delete. Purchased components remain protected from authoritative geometry rewriting. | `e2e/feature-history-ux.spec.ts` |
| P0 | The v3.1 feature editor mutates feature parameters with HTTP `PATCH`, while the legacy desktop CORS allow-list omitted `PATCH`. | Feature creation could succeed while editing an existing feature could fail at the renderer/engine boundary. | Desktop entrypoint now adds the complete mutable desktop CORS method set, including `PATCH`, without changing route semantics. | Browser regression performs a real feature `PATCH` and verifies canonical state |
| P1 | Embedded Code was constrained to the generic 238px bottom tray. | The built-in IDE existed but was not a credible primary programming surface. | Code dock expands to at least 310px / 44vh at normal desktop heights, with a 250px / 42vh fallback at the packaged 760px minimum height. | Existing code/branch persistence regression plus layout gate |
| P1 | Physical World/System inspector shared the same shallow generic tray. | Entity, provenance, live state, relations, and graph status were compressed into an impractical viewport. | System dock expands to at least 280px / 38vh when the world inspector is active. | Existing world-system/integration coverage plus layout gate |
| P1 | Branch browser terminology said “DESIGNS” while the rest of ForgeCAD uses branch semantics. | The same canonical concept appeared to be two different concepts. | Browser section is now **BRANCHES**; branch picker and lineage panel use the same language. | Lineage UX regression |
| P1 | Several important inputs/selects lacked explicit accessible names. | Keyboard/assistive navigation and stable automated acceptance were weaker than the visual UI. | Added explicit labels for branch selection and component search/category/voltage controls; new lineage controls are fully labeled. | Playwright role/name selection |
| P1 | Copilot submission previously had high interaction-risk around Enter/Shift+Enter, model-offline behavior, and concurrent jobs. | Drafts could be lost or the visible agent state could become misleading. | Existing 6.0.1 revisions preserve Shift+Enter newline, Enter send, offline draft retention, cancellation/status presentation, and separation between Copilot and engineering jobs. | `e2e/ux-regression.spec.ts` |
| P1 | Delete and branch-switch operations had state-integrity risks. | UI could lag canonical deletion or switch branches before embedded code finished saving. | Existing 6.0.1 revisions use optimistic ID-based deletion with rollback and make branch switching wait for in-flight code save. | `e2e/ux-regression.spec.ts` |
| P1 | Keyboard operations were powerful but insufficiently discoverable. | Users could trigger or miss shortcuts without a coherent reference. | Existing 6.0.1 Keyboard Shortcuts surface and toast/notice system retained; toolbar shortcut entry remains visible. | `e2e/keyboard-shortcuts.spec.ts` |
| P2 | The packaged window minimum is 1280×760 while the shell was primarily tuned at desktop-design width. | Small-window use risks excessive density. | Existing 1380px contraction is retained; Code now has a 760px-height-specific fallback. Audit uses 1280×760 as the hard desktop acceptance floor rather than mobile-web behavior. | Desktop window config + visual/layout acceptance |
| P2 | Repository top-level release messaging is older than the 6.0.1 branch state. | Developers can enter the correct product through stale documentation and form the wrong release mental model. | Documentation cleanup remains part of the release-close pass; `docs/RELEASE_6_0_1.md` and this audit are authoritative for 6.0.1 until the README is reconciled. | Release-close review |

## Information architecture after revision

### Left: model and intent

The left side owns the design tree, branch navigation, and Engineering Copilot. Branches are not treated as Git refs; they are snapshots of the canonical engineering state. The **Manage** affordance leads to full design-lineage controls without turning the model tree into a configuration form.

### Center: the physical artifact

The center remains the primary 3D canvas. Selection is shared with the model tree and Properties. Bottom surfaces are contextual workspaces rather than generic drawers: History for chronology, Code for programmable hardware, Simulation for long-running engineering jobs, System for canonical physical/deployed state.

### Right: inspect, source, verify, manufacture

**Properties** owns selected-object identity/physical data, editable fabricated CAD feature history, design-state truth, and branch lineage. **Components** owns real-world part discovery and insertion. **Analyze** owns validation and engineering evidence. **Manufacture** owns manufacturing-resource checks and redesign handoff.

This separation intentionally keeps purchased-component provenance and fabricated-part feature editing distinct. A purchased component may expose code and engineering interfaces, but its authoritative supplier geometry is not silently converted into editable custom geometry.

## Truth and safety invariants

- “Working” and “not working” are user/design lineage labels, not evidence of physical verification.
- Physical verification remains independently evidence-bound and revision-bound.
- Branch comparison reads canonical project state; it is not a DOM or visual diff.
- Feature-history mutations go through Forge Engine and cause the project/scene revision to refresh.
- Embedded code remains branch-owned canonical engineering state; branch switching may not race an in-flight save.
- Purchased components remain protected from geometry operations that would falsify supplier identity or provenance.
- World/live observations remain distinct from designed state and from inferred state.

## 6.0.1 UX acceptance gate

The release UX workflow now runs desktop typecheck, unit tests, production build, canonical branch persistence self-test, the focused interaction suite, design-lineage acceptance, fabricated feature-history acceptance, keyboard-shortcut acceptance, and the preserved 3.1 browser integration suite. The focused browser tests run serially because they deliberately mutate one canonical local Forge Engine project.

Release close requires the latest branch head to pass those gates after the final UX commit. Native packaging/release workflows remain separate and must also be green before installers are treated as release artifacts.
