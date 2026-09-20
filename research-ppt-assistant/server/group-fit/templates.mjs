const round = (value) => Number(value.toFixed(6));

function insetBox(group, left, top, width, height) {
  return {
    x: round(group.x + group.width * left),
    y: round(group.y + group.height * top),
    width: round(group.width * width),
    height: round(group.height * height),
  };
}

function grid2x2(group, columnRatio, rowRatio, gapRatio) {
  const gx = gapRatio;
  const gy = gapRatio * (group.width / group.height);
  const leftWidth = columnRatio - gx / 2;
  const rightWidth = 1 - columnRatio - gx / 2;
  const topHeight = rowRatio - gy / 2;
  const bottomHeight = 1 - rowRatio - gy / 2;
  return [
    insetBox(group, 0, 0, leftWidth, topHeight),
    insetBox(group, columnRatio + gx / 2, 0, rightWidth, topHeight),
    insetBox(group, 0, rowRatio + gy / 2, leftWidth, bottomHeight),
    insetBox(group, columnRatio + gx / 2, rowRatio + gy / 2, rightWidth, bottomHeight),
  ];
}

function onePlusThree(group, primaryOnLeft, gapRatio) {
  const primaryWidth = 0.55;
  const gx = gapRatio;
  const gy = gapRatio * (group.width / group.height);
  const stackWidth = 1 - primaryWidth - gx;
  const stackHeight = (1 - 2 * gy) / 3;
  const left = primaryOnLeft ? 0 : stackWidth + gx;
  const stackLeft = primaryOnLeft ? primaryWidth + gx : 0;
  return [
    insetBox(group, left, 0, primaryWidth, 1),
    insetBox(group, stackLeft, 0, stackWidth, stackHeight),
    insetBox(group, stackLeft, stackHeight + gy, stackWidth, stackHeight),
    insetBox(group, stackLeft, 2 * (stackHeight + gy), stackWidth, stackHeight),
  ];
}

function twoPlusOne(group, gapRatio) {
  const gx = gapRatio;
  const gy = gapRatio * (group.width / group.height);
  const halfWidth = (1 - gx) / 2;
  const topHeight = 0.48 - gy / 2;
  return [
    insetBox(group, 0, 0, halfWidth, topHeight),
    insetBox(group, halfWidth + gx, 0, halfWidth, topHeight),
    insetBox(group, 0, 0.48 + gy / 2, 1, 0.52 - gy / 2),
  ];
}

export const PREDEFINED_ASYMMETRIC_TEMPLATES = Object.freeze([
  "ASYM-2X2-LEFT_WIDE",
  "ASYM-2X2-RIGHT_WIDE",
  "ASYM-TOP_WIDE",
  "ASYM-BOTTOM_WIDE",
  "ASYM-1PLUS3",
  "ASYM-2PLUS1",
]);

export function generateAsymmetricCandidates({ group_bbox: group, child_ids: childIds, gap_ratio: gapRatio = 0.02 } = {}) {
  if (!group || !Array.isArray(childIds)) return [];
  const definitions = [];
  if (childIds.length === 4) {
    definitions.push(
      ["ASYM-2X2-LEFT_WIDE", grid2x2(group, 0.67, 0.5, gapRatio)],
      ["ASYM-2X2-RIGHT_WIDE", grid2x2(group, 0.33, 0.5, gapRatio)],
      ["ASYM-TOP_WIDE", grid2x2(group, 0.5, 0.67, gapRatio)],
      ["ASYM-BOTTOM_WIDE", grid2x2(group, 0.5, 0.33, gapRatio)],
      ["ASYM-1PLUS3", onePlusThree(group, true, gapRatio)],
    );
  } else if (childIds.length === 3) {
    definitions.push(["ASYM-2PLUS1", twoPlusOne(group, gapRatio)]);
  }
  return definitions.map(([layoutId, boxes]) => ({
    layout_id: layoutId,
    group_bbox: group,
    allocations: childIds.map((visualId, index) => ({ visual_id: visualId, allocated_visual_bbox: boxes[index] })),
    child_order: [...childIds],
    higher_priority_issues: { content_integrity: 0, legibility: 0 },
    source: "predefined_asymmetric_template",
  }));
}
