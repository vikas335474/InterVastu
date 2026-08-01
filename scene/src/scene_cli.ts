/**
 * CLI: node scene_cli.ts <scene_input.json> <output_scene.json>
 *
 * Builds the scene and persists it via three.js's own Object3D JSON format
 * (`scene.toJSON()`), reloadable with `THREE.ObjectLoader` — the "scene
 * file for reuse" deliverable, kept separate from build_scene.ts (which
 * must stay Node-free so it can also be bundled for the browser by
 * export_views.ts).
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import type * as THREE from 'three';

import { buildScene } from './build_scene.js';
import type { SceneInput } from './types.js';

export function saveSceneJSON(scene: THREE.Scene, outputPath: string): void {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify(scene.toJSON()));
}

function isMainModule(): boolean {
  return process.argv[1] === fileURLToPath(import.meta.url);
}

if (isMainModule()) {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) {
    console.error('usage: node scene_cli.ts <scene_input.json> <output_scene.json>');
    process.exit(1);
  }
  const input = JSON.parse(fs.readFileSync(inputPath, 'utf-8')) as SceneInput;
  const { scene } = buildScene(input);
  saveSceneJSON(scene, outputPath);
  console.log(`wrote ${outputPath}`);
}
