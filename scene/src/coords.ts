import * as THREE from 'three';

/**
 * Plan (x, y) -> Three.js (x, height, z) mapping used everywhere in this
 * module: plan-x stays x, plan-y (local "north") becomes -z, and the
 * explicit height parameter becomes the vertical (up) axis. Every module
 * that places geometry MUST go through this function so the mapping stays
 * single-sourced.
 */
export function planToThree(x: number, y: number, heightFt = 0): THREE.Vector3 {
  return new THREE.Vector3(x, heightFt, -y);
}

/**
 * Three.js Y-axis rotation (radians) for an object whose local +Z ("front")
 * should point toward compass bearing `bearingDeg` (0 = North, clockwise),
 * consistent with planToThree's (x, y) -> (x, -y) mapping.
 *
 * Derivation: bearing b has plan direction (sin b, cos b) [matches
 * zone_geometry.local_bearing_deg's atan2(dx, dy) convention], which maps to
 * three-space direction (sin b, 0, -cos b). Three's +Y rotation by theta
 * sends local +Z=(0,0,1) to (sin theta, 0, cos theta). Solving
 * sin theta = sin b, cos theta = -cos b gives theta = 180deg - b.
 */
export function bearingDegToThreeYRotation(bearingDeg: number): number {
  return THREE.MathUtils.degToRad(180 - bearingDeg);
}

export function polygonCentroid(polygon: [number, number][]): [number, number] {
  let area = 0;
  let cx = 0;
  let cy = 0;
  const n = polygon.length;
  for (let i = 0; i < n; i++) {
    const [x0, y0] = polygon[i];
    const [x1, y1] = polygon[(i + 1) % n];
    const cross = x0 * y1 - x1 * y0;
    area += cross;
    cx += (x0 + x1) * cross;
    cy += (y0 + y1) * cross;
  }
  area *= 0.5;
  if (Math.abs(area) < 1e-9) {
    // Degenerate polygon: fall back to the vertex average.
    const sum = polygon.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0]);
    return [sum[0] / n, sum[1] / n];
  }
  return [cx / (6 * area), cy / (6 * area)];
}

export function polygonBounds(polygon: [number, number][]): [number, number, number, number] {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of polygon) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return [minX, minY, maxX, maxY];
}
