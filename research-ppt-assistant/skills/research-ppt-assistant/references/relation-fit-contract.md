# Relation-aware Group Fit Contract

Use this reference for RPA 0.4.6 pages containing two or more semantically related sibling visuals.

## Boundary

The pipeline remains deterministic:

```text
v0.4.5 baseline candidate
→ per-child Visual Fit
→ Group Fit metrics
→ relation–fit conflict rule
→ one-pass Constraint Arbitration
→ selected candidate or v0.4.5 fallback
```

Group Fit does not rewrite the Planner, create free-form geometry, split a slide, reorder evidence, remove content, or choose a semantic crop. The priority order is Content Integrity > Legibility > Visual Fit > Semantic Relation > Balance > Symmetry > Decoration.

## Relation and geometry are separate

`visual_group` declares meaning and ordered membership:

```json
{
  "group_id": "robustness-evidence",
  "semantic_relation": "parallel",
  "relation_strength": "soft",
  "children": ["uv-aging", "dye-comparison", "temperature", "stretching"]
}
```

`layout_relation` independently declares geometry:

```json
{
  "shared_alignment": true,
  "shared_container_style": true,
  "equal_size": false,
  "equal_width": false,
  "equal_height": false,
  "preserve_order": true,
  "intentional_unequal_weight": true
}
```

Never infer equality fields from `semantic_relation`. `hard` preserves pairing/order and cannot be automatically relaxed. `soft` may relax equality geometry while preserving membership, semantic level, reading order, and shared alignment. `advisory` allows broader predefined candidates but retains the same safety boundary.

## Candidate contract

Always supply a complete `baseline_candidate` containing its `layout_id`, optional `group_bbox`, and exactly one `allocated_visual_bbox` for every ordered child. This is the immutable v0.4.5 path. Optional `relation_aware_candidates` use the same shape. Built-in alternatives are restricted to the predefined `ASYM-*` family and are generated only when `non_uniform_siblings` is enabled and the baseline has a `group_bbox`.

Every Child continues through the 0.4.5 Visual Fit metric/rule boundary. Group metrics are facts only:

- `group_min_fill`, `group_max_fill`, `group_mean_fill`
- `group_fill_variance`
- `fit_equity = min(fill) / max(fill)`
- `visual_weight_deviation`

Quality Profile 1.4 `relation_fit_rules` owns conflict, minimum-gain, maximum-weight-deviation, replan-limit, template-gap, and credits thresholds.

## Decisions

- `preserve_v045_baseline`: no relation–fit conflict; do not churn the layout.
- `shadow_preserve_v045`: report the candidate in `would_select_candidate`, but render baseline.
- `select_relation_aware_candidate`: deterministic candidate resolves the conflict without a higher-priority regression.
- `fallback_to_v045`: alternatives are marginal, unsafe, still conflicting, or order-breaking.
- `needs_replan`: hard relation cannot be safely resolved, or fallback is disabled.
- `feature_disabled`: a required v0.4.6 feature flag is off; treat the baseline as authoritative.

`VISUAL_RELATION_FIT_CONFLICT` identifies the baseline constraint conflict. When a selected candidate resolves it, it appears under `resolved_issues`; unresolved conflicts remain under `issues`.

## Feature flags and loop bound

The supported flags are `visual_fit_v045`, `relation_contract_v046`, `group_fit_preflight`, `relation_arbitration`, `non_uniform_siblings`, and `fallback_to_v045`. `relation_arbitration` accepts `false`, `true`, or `"shadow"`; Shadow is the safe rollout default. `max_relation_replan_attempts` is normally 1 and can never exceed 2.

## Telemetry and release gates

Read `relation_fit` for child fill, equity, variance and conflict facts. Read `constraint_arbitration` for relaxed/preserved constraints, original/selected/would-select candidates, fallback, Shadow state, and bounded attempt count. `credits_regression` compares median credits/deck against the Quality Profile limit; missing credit facts remain `not_evaluable`.

Release qualification requires all eight Relation Challenge probes, deterministic output, conflict precision/recall, zero churn on the v0.4.5 good-page set, credits/deck at or below 110% of v0.4.5, and Group Fit P95 below the shared 50 ms single-slide limit.
