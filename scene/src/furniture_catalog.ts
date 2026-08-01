/**
 * Placeholder furniture dimensions (width x depth x height, feet) keyed by
 * solver.py's `object` field. These are rough real-world footprints for
 * PLACEHOLDER boxes only — swapping in real licensed furniture meshes
 * (correct silhouette, materials) is a separate, later content-sourcing
 * task and is not blocked by anything here. Position/rotation are exact
 * and authoritative; box geometry is not.
 *
 * width  = extent along the object's local X (the wall it's flush against)
 * depth  = extent along the object's local Z (into the room, "front" axis
 *          used by bearingDegToThreeYRotation)
 * height = vertical extent
 */
export interface FurnitureDims {
  width: number;
  depth: number;
  height: number;
  /** Height of the box's own local origin above the floor, in feet. */
  elevation: number;
}

export const FURNITURE_CATALOG: Record<string, FurnitureDims> = {
  bed: { width: 6.5, depth: 6.5, height: 2, elevation: 0 },
  stove: { width: 2.5, depth: 2, height: 3, elevation: 0 },
  // solver.py's LivingRoom output recommends a WALL, not a specific piece;
  // rendered as a generic heavy-furniture placeholder (console/cabinet-scale
  // box) occupying that wall's zone.
  heavy_furniture_zone: { width: 6, depth: 1.5, height: 2.5, elevation: 0 },
};

/** Small fallback box for any object type not yet in the catalog above. */
export const DEFAULT_FURNITURE_DIMS: FurnitureDims = {
  width: 2,
  depth: 2,
  height: 2.5,
  elevation: 0,
};

export function dimsForObject(objectType: string): FurnitureDims {
  return FURNITURE_CATALOG[objectType] ?? DEFAULT_FURNITURE_DIMS;
}
