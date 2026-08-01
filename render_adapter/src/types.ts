/**
 * Vendor-agnostic AI render-styling interface.
 *
 * No real vendor is wired in yet — a Phase-0 bake-off/spike (Replicate,
 * PromeAI, or others) is still pending. This interface exists so the rest
 * of the pipeline (batching, cost tracking, drift-checking) can be built
 * and tested against `MockStylingProvider` before any vendor contract or
 * API key exists. When a vendor is selected, add a new
 * `providers/<vendor>_provider.ts` implementing this same interface — no
 * other module in this repo should need to change.
 */

export interface StyleImageInput {
  /** Path to the depth-map PNG from scene/'s export_views.ts pipeline. */
  depthMapPath: string;
  /** Optional reference/color image path (e.g. the matching color render). */
  colorMapPath?: string;
  /** e.g. "contemporary minimalist, warm wood tones, soft daylight". */
  stylePrompt: string;
  /** 0-1: how strictly the output must follow the depth map vs. the prompt. */
  conditioningStrength: number;
}

export interface StyleImageResult {
  imagePath: string;
  providerName: string;
  costEstimate?: number;
  rawResponseMeta?: object;
}

export interface StylingProvider {
  styleImage(input: StyleImageInput): Promise<StyleImageResult>;
}
