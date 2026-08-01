/**
 * Geometry drift check — STUB.
 *
 * The scene assembled in the previous session (`scene/`) is EXACT geometry
 * that a styling vendor must only re-texture, never move. To actually
 * verify that after the fact, this function needs to:
 *
 *   TODO(real implementation, blocked on vendor spike):
 *   1. Re-run a monocular depth-estimation model (e.g. an open
 *      MiDaS-family model) on `styledImagePath` to recover its implied
 *      depth map.
 *   2. Compare that recovered depth map against `originalDepthMapPath`
 *      (e.g. structural similarity / SSIM, or an edge-alignment score
 *      between the two depth maps' silhouettes) to detect whether the
 *      vendor moved walls/furniture or invented geometry that wasn't in
 *      the original scene.
 *   3. Turn the raw similarity/edge score into a pass/fail threshold
 *      (and probably a per-room or per-object breakdown, not just a
 *      single scalar).
 *
 * This is deliberately NOT implemented yet: picking and validating a
 * specific depth-estimation model is real, non-trivial work, and doing it
 * now would be premature — it should happen once the Phase-0 bake-off
 * picks a real styling vendor, since the choice may depend on that
 * vendor's typical failure modes (e.g. how aggressively a given model
 * tends to invent geometry). Until then, this stub returns a fixed
 * placeholder result so the rest of the pipeline (which needs a
 * `checkGeometryDrift` to call) can be built and tested against it.
 */
import * as fs from 'node:fs';

export interface DriftCheckResult {
  /** Always null until the real implementation lands — see TODO above. */
  driftScore: number | null;
  /** Always true for the stub: it never actually detects drift. */
  passed: boolean;
  method: 'stub';
  note: string;
}

export async function checkGeometryDrift(
  originalDepthMapPath: string,
  styledImagePath: string,
): Promise<DriftCheckResult> {
  for (const p of [originalDepthMapPath, styledImagePath]) {
    if (!fs.existsSync(p)) {
      throw new Error(`checkGeometryDrift: file does not exist: ${p}`);
    }
  }

  return {
    driftScore: null,
    passed: true,
    method: 'stub',
    note:
      'STUB — no geometry comparison was actually performed. Real implementation ' +
      'needs to re-run a monocular depth-estimation model (e.g. MiDaS-family) on ' +
      'the styled output and compare it against the original depth map (SSIM or ' +
      'edge-alignment scoring). Deferred until the Phase-0 vendor spike lands, ' +
      'since the failure modes worth checking for depend on which vendor is chosen.',
  };
}
