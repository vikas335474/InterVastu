/**
 * Input/output shapes for the deterministic 3D scene assembly layer.
 *
 * Conventions (must match `genesis/engine/zone_geometry.py` and
 * `genesis/engine/solver.py` exactly — this module does no re-projection):
 *   - All lengths are in FEET.
 *   - Room polygons are lists of (x, y) vertices in the room-local plan
 *     frame: +x = plan-right, +y = plan-up ("north" when facade_bearing=0).
 *   - `rotation_deg` on furniture is a compass bearing (0 = North,
 *     clockwise), exactly as produced by solver.py, and is interpreted in
 *     the SAME local frame as the polygons (i.e. this module assumes the
 *     input has already been rotated onto true north if that mattered —
 *     it does not re-apply a facade_bearing correction).
 *   - Wall edges follow zone_geometry/solver's own polygon-edge convention:
 *     edge `i` runs from vertex `i` to vertex `(i + 1) % n`.
 */

export type Coord = [number, number];

export interface RoomInput {
  name: string;
  polygon: Coord[];
  /** Wall height in feet for this room. Falls back to the scene default (10 ft). */
  wall_height_ft?: number;
}

export interface OpeningInput {
  room: string;
  /** Index of the polygon edge (wall segment) this opening is cut into. */
  wall_index: number;
  /** Distance in feet from the edge's start vertex to the opening's near edge. */
  offset_ft: number;
  width_ft: number;
  type: 'door' | 'window';
  /** Height of the opening's sill above the floor, in feet. Doors default to 0. */
  sill_height_ft?: number;
  /** Height of the opening's head above the floor, in feet. */
  head_height_ft?: number;
}

/** Matches solver.py's per-item output shape exactly — do not diverge. */
export interface FurniturePlacement {
  room: string;
  object: string;
  position: Coord;
  rotation_deg: number;
  satisfies_rule?: boolean;
  compromise?: boolean;
  compromise_note?: string | null;
}

export interface SceneInput {
  rooms: RoomInput[];
  /** Default wall height in feet, used for any room that doesn't override it. */
  wall_height_ft?: number;
  openings?: OpeningInput[];
  furniture?: FurniturePlacement[];
}

export interface RoomMeta {
  name: string;
  polygon: Coord[];
  centroid: Coord;
  /** [minX, minY, maxX, maxY] in feet. */
  bounds: [number, number, number, number];
  wallHeightFt: number;
}

export interface SceneBuildResult {
  rooms: RoomMeta[];
}

/** A single fixed camera view to render, in three.js world space (feet). */
export interface ViewConfig {
  roomName: string;
  /** [x, y, z] camera position in three.js world space. */
  position: [number, number, number];
  /** [x, y, z] look-at target in three.js world space. */
  target: [number, number, number];
  fovDeg: number;
  near: number;
  far: number;
  width: number;
  height: number;
}

/** What the browser render entry hands back to Node for one view. */
export interface ViewRenderResult {
  roomName: string;
  width: number;
  height: number;
  /** data:image/png;base64,... from canvas.toDataURL() — the color pass. */
  colorDataUrl: string;
  /** Raw RGBA bytes (base64), WebGL readPixels order (bottom row first). */
  depthRawRgbaBase64: string;
}
