/**
 * Bundled (via esbuild) into an IIFE and injected into a headless Playwright
 * page. Builds the three.js scene from the same `buildScene` used on the
 * Node side and renders each requested view's color pass and depth pass.
 *
 * This file must stay browser-only (no Node built-ins) since esbuild
 * bundles it for `platform: 'browser'`.
 */
import * as THREE from 'three';
import { buildScene } from '../build_scene.js';
import type { SceneInput, ViewConfig, ViewRenderResult } from '../types.js';

function uint8ToBase64(bytes: Uint8Array): string {
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

async function renderRoomViews(
  sceneInput: SceneInput,
  views: ViewConfig[],
): Promise<ViewRenderResult[]> {
  const { scene } = buildScene(sceneInput);
  const results: ViewRenderResult[] = [];

  for (const view of views) {
    const canvas = document.createElement('canvas');
    canvas.width = view.width;
    canvas.height = view.height;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    renderer.setSize(view.width, view.height, false);

    const camera = new THREE.PerspectiveCamera(view.fovDeg, view.width / view.height, view.near, view.far);
    camera.position.set(...view.position);
    camera.up.set(0, 1, 0);
    camera.lookAt(new THREE.Vector3(...view.target));

    // --- Color pass ---
    scene.overrideMaterial = null;
    renderer.render(scene, camera);
    const colorDataUrl = canvas.toDataURL('image/png');

    // --- Depth pass: a custom linear-depth shader, not THREE.MeshDepthMaterial's
    // default BasicDepthPacking. BasicDepthPacking outputs nonlinear NDC depth,
    // which (for typical near/far ratios) compresses almost the entire visible
    // range into a few of the 256 gray levels near 0 — nearly useless as an
    // actual "distance from camera" signal. This shader instead writes
    // view-space depth (camera-forward distance) linearly normalized between
    // camera.near and camera.far, so pixel value is proportional to distance.
    scene.overrideMaterial = new THREE.ShaderMaterial({
      uniforms: { uNear: { value: view.near }, uFar: { value: view.far } },
      vertexShader: `
        varying float vLinearDepth;
        void main() {
          vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
          vLinearDepth = -mvPosition.z;
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        uniform float uNear;
        uniform float uFar;
        varying float vLinearDepth;
        void main() {
          float d = clamp((vLinearDepth - uNear) / (uFar - uNear), 0.0, 1.0);
          gl_FragColor = vec4(vec3(d), 1.0);
        }
      `,
      side: THREE.DoubleSide,
    });
    renderer.render(scene, camera);
    scene.overrideMaterial = null;

    const gl = renderer.getContext();
    const rgba = new Uint8Array(view.width * view.height * 4);
    gl.readPixels(0, 0, view.width, view.height, gl.RGBA, gl.UNSIGNED_BYTE, rgba);

    results.push({
      roomName: view.roomName,
      width: view.width,
      height: view.height,
      colorDataUrl,
      depthRawRgbaBase64: uint8ToBase64(rgba),
    });

    renderer.dispose();
  }

  return results;
}

(window as any).__renderRoomViews = renderRoomViews;
