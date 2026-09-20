const geometryConstraints = (layoutRelation) => ["equal_size", "equal_width", "equal_height"].filter((key) => layoutRelation[key] === true);

export const GROUP_FIT_GEOMETRY_EPSILON = 1e-6;

function contains(outer, inner, epsilon = GROUP_FIT_GEOMETRY_EPSILON) {
  return outer.x <= inner.x + epsilon
    && outer.y <= inner.y + epsilon
    && outer.x + outer.width >= inner.x + inner.width - epsilon
    && outer.y + outer.height >= inner.y + inner.height - epsilon;
}

function intersection(left, right, epsilon = GROUP_FIT_GEOMETRY_EPSILON) {
  const x = Math.max(left.x, right.x);
  const y = Math.max(left.y, right.y);
  const rightEdge = Math.min(left.x + left.width, right.x + right.width);
  const bottomEdge = Math.min(left.y + left.height, right.y + right.height);
  if (rightEdge - x <= epsilon || bottomEdge - y <= epsilon) return null;
  return { x, y, width: rightEdge - x, height: bottomEdge - y };
}

function sameBox(left, right, epsilon = GROUP_FIT_GEOMETRY_EPSILON) {
  return ["x", "y", "width", "height"].every((key) => Math.abs(left[key] - right[key]) <= epsilon);
}

/** Check the geometry invariants for independent visual siblings in one group. */
export function evaluateCandidateGeometry(candidate, referenceGroupBBox = null, epsilon = GROUP_FIT_GEOMETRY_EPSILON) {
  const candidateGroupBBox = candidate?.group_bbox ?? null;
  const groupBBox = referenceGroupBBox ?? candidateGroupBBox;
  const issues = [];
  if (referenceGroupBBox && candidateGroupBBox && !sameBox(referenceGroupBBox, candidateGroupBBox, epsilon)) {
    issues.push({
      code: "group_bbox_changed",
      group_bbox: candidateGroupBBox,
      reference_group_bbox: referenceGroupBBox,
    });
  }
  const allocations = Array.isArray(candidate?.allocations) ? candidate.allocations : [];
  if (groupBBox) {
    for (const allocation of allocations) {
      const box = allocation.allocated_visual_bbox;
      if (!contains(groupBBox, box, epsilon)) {
        issues.push({
          code: "allocation_out_of_group_bounds",
          visual_id: allocation.visual_id,
          allocated_visual_bbox: box,
          group_bbox: groupBBox,
        });
      }
    }
  }
  for (let leftIndex = 0; leftIndex < allocations.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < allocations.length; rightIndex += 1) {
      const left = allocations[leftIndex];
      const right = allocations[rightIndex];
      const overlap = intersection(left.allocated_visual_bbox, right.allocated_visual_bbox, epsilon);
      if (!overlap) continue;
      const leftContainsRight = contains(left.allocated_visual_bbox, right.allocated_visual_bbox, epsilon);
      const rightContainsLeft = contains(right.allocated_visual_bbox, left.allocated_visual_bbox, epsilon);
      issues.push({
        code: "sibling_allocations_overlap",
        visual_ids: [left.visual_id, right.visual_id],
        overlap_kind: leftContainsRight || rightContainsLeft ? "contained" : "crossing",
        overlap_bbox: overlap,
      });
    }
  }
  return {
    measurable: Boolean(groupBBox),
    valid: issues.length === 0,
    group_bbox: groupBBox,
    issues,
  };
}

export function evaluateRelationFitConflict(candidate, relation, layoutRelation, profile) {
  const rule = profile?.group_fit;
  if (!rule) throw new TypeError("relation fit profile requires group_fit thresholds");
  const constrainedByEquality = geometryConstraints(layoutRelation);
  if (layoutRelation.intentional_unequal_weight || constrainedByEquality.length === 0) {
    return {
      conflict: false,
      status: "pass",
      reason: layoutRelation.intentional_unequal_weight ? "intentional_unequal_visual_weight" : "no_geometric_equality_constraint",
      conflicting_children: [],
      geometry_constraints: constrainedByEquality,
    };
  }
  const conflictingChildren = candidate.child_fit
    .filter((child) => child.status === "fail" || child.fill < rule.minimum_child_fill_fail)
    .map((child) => child.visual_id);
  const distributionConflict = candidate.metrics.group_min_fill < rule.minimum_child_fill_fail
    && candidate.metrics.fit_equity < rule.fit_equity_fail;
  const conflict = conflictingChildren.length > 0 || distributionConflict;
  if (conflict) {
    return {
      conflict: true,
      status: "fail",
      reason: "semantic_relation_geometry_causes_child_fit_failure",
      conflicting_children: conflictingChildren.length ? conflictingChildren : candidate.child_fit.filter((child) => child.fill === candidate.metrics.group_min_fill).map((child) => child.visual_id),
      geometry_constraints: constrainedByEquality,
    };
  }
  const warning = candidate.metrics.group_min_fill < rule.minimum_child_fill_warning
    || candidate.metrics.fit_equity < rule.fit_equity_warning
    || candidate.metrics.group_fill_variance > rule.group_fill_variance_warning;
  return {
    conflict: false,
    status: warning ? "warning" : "pass",
    reason: warning ? "group_fit_distribution_requires_inspection" : "relation_and_visual_fit_compatible",
    conflicting_children: [],
    geometry_constraints: constrainedByEquality,
  };
}

function orderPreserved(candidate, childIds) {
  return candidate.child_order.length === childIds.length && candidate.child_order.every((id, index) => id === childIds[index]);
}

export function compareRelationCandidate({ baseline, candidate, relation, layoutRelation, childIds, profile }) {
  const rule = profile?.arbitration;
  if (!rule) throw new TypeError("relation fit profile requires arbitration thresholds");
  const gain = candidate.gain;
  const rejections = [];
  if (candidate.geometry && !candidate.geometry.valid) {
    rejections.push(...candidate.geometry.issues.map((issue) => issue.code));
  }
  if (!orderPreserved(candidate, childIds)) rejections.push("reading_order_changed");
  if (candidate.higher_priority_issues.content_integrity > baseline.higher_priority_issues.content_integrity) rejections.push("content_integrity_regression");
  if (candidate.higher_priority_issues.legibility > baseline.higher_priority_issues.legibility) rejections.push("legibility_regression");
  if (candidate.metrics.visual_weight_deviation > rule.maximum_visual_weight_deviation) rejections.push("semantic_weight_deviation_exceeded");
  if (gain.minimum_fill_gain < rule.minimum_gain && candidate.conflict.conflict === baseline.conflict.conflict) rejections.push("minimum_gain_not_met");
  if (candidate.conflict.conflict) rejections.push("relation_fit_conflict_unresolved");
  if (relation.relation_strength === "hard" && geometryConstraints(layoutRelation).some((key) => candidate.relaxed_constraints.includes(key))) {
    rejections.push("hard_relation_would_be_relaxed");
  }
  const baselineSevere = Number(baseline.conflict.conflict) + (baseline.geometry?.issues.length ?? 0) + baseline.child_fit.filter((child) => child.status === "fail").length
    + baseline.higher_priority_issues.content_integrity + baseline.higher_priority_issues.legibility;
  const candidateSevere = Number(candidate.conflict.conflict) + (candidate.geometry?.issues.length ?? 0) + candidate.child_fit.filter((child) => child.status === "fail").length
    + candidate.higher_priority_issues.content_integrity + candidate.higher_priority_issues.legibility;
  if (candidateSevere > baselineSevere) rejections.push("severe_issue_count_increased");
  if (baseline.conflict.conflict && candidateSevere >= baselineSevere && gain.minimum_fill_gain < rule.minimum_gain) rejections.push("not_monotonic_improvement");
  return {
    accepted: rejections.length === 0,
    rejections: [...new Set(rejections)],
    severe_issue_count: candidateSevere,
    baseline_severe_issue_count: baselineSevere,
  };
}

export function relaxedGeometryConstraints(layoutRelation) {
  return geometryConstraints(layoutRelation);
}
