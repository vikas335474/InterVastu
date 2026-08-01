/**
 * Deterministic 3D scene assembly.
 *
 * Extrudes room polygons into wall/floor/ceiling geometry and places
 * placeholder furniture boxes from a solver.py-shaped placement list. This
 * module produces EXACT, final geometry — a later AI styling step only
 * re-textures what's built here, it never moves anything. No visual
 * polish, no architectural detail beyond plain box extrusion.
 */
import * as THREE from 'three';

import { bearingDegToThreeYRotation, planToThree, polygonBounds, polygonCentroid } from './coords.js';
import { dimsForObject } from './furniture_catalog.js';
import type { Coord, OpeningInput, RoomInput, RoomMeta, SceneInput } from './types.js';

export const DEFAULT_WALL_HEIGHT_FT = 10;
/** Wall thickness, centered on the polygon edge (the boundary line itself). */
export const WALL_THICKNESS_FT = 0.5;

const WALL_MATERIAL = new THREE.MeshStandardMaterial({ color: 0xd9d2c7, side: THREE.DoubleSide });
const FLOOR_MATERIAL = new THREE.MeshStandardMaterial({ color: 0xa89078, side: THREE.DoubleSide });
const CEILING_MATERIAL = new THREE.MeshStandardMaterial({ color: 0xf5f5f0, side: THREE.DoubleSide });
const FURNITURE_MATERIAL = new THREE.MeshStandardMaterial({ color: 0x6f8faa, side: THREE.DoubleSide });

interface Span {
  /** Distance along the wall edge, from the edge's start vertex, in feet. */
  start: number;
  end: number;
}

/**
 * The unobstructed spans of a wall edge after cutting out openings.
 * Openings punch a full-height gap through the wall — no lintel/sill
 * partial-wall geometry, per the "no architectural detail" scope.
 */
function wallSpansWithOpenings(edgeLength: number, openings: OpeningInput[]): Span[] {
  const cuts = openings
    .map((o) => ({ start: Math.max(0, o.offset_ft), end: Math.min(edgeLength, o.offset_ft + o.width_ft) }))
    .filter((c) => c.end > c.start)
    .sort((a, b) => a.start - b.start);

  const spans: Span[] = [];
  let cursor = 0;
  for (const cut of cuts) {
    if (cut.start > cursor) spans.push({ start: cursor, end: cut.start });
    cursor = Math.max(cursor, cut.end);
  }
  if (cursor < edgeLength) spans.push({ start: cursor, end: edgeLength });
  return spans;
}

function buildWallsForRoom(
  room: RoomInput,
  wallHeightFt: number,
  openings: OpeningInput[],
): THREE.Mesh[] {
  const meshes: THREE.Mesh[] = [];
  const n = room.polygon.length;

  for (let i = 0; i < n; i++) {
    const p1 = room.polygon[i];
    const p2 = room.polygon[(i + 1) % n];
    const dx = p2[0] - p1[0];
    const dy = p2[1] - p1[1];
    const edgeLength = Math.hypot(dx, dy);
    if (edgeLength < 1e-9) continue;

    const edgeOpenings = openings.filter((o) => o.wall_index === i);
    const spans = wallSpansWithOpenings(edgeLength, edgeOpenings);
    const rotationY = Math.atan2(dy, dx);
    const ux = dx / edgeLength;
    const uy = dy / edgeLength;

    for (const span of spans) {
      const segLength = span.end - span.start;
      if (segLength < 1e-6) continue;
      const midDist = (span.start + span.end) / 2;
      const midX = p1[0] + ux * midDist;
      const midY = p1[1] + uy * midDist;

      const geometry = new THREE.BoxGeometry(segLength, wallHeightFt, WALL_THICKNESS_FT);
      const mesh = new THREE.Mesh(geometry, WALL_MATERIAL);
      mesh.position.copy(planToThree(midX, midY, wallHeightFt / 2));
      mesh.rotation.y = rotationY;
      mesh.name = `wall:${room.name}:${i}:${span.start.toFixed(3)}-${span.end.toFixed(3)}`;
      meshes.push(mesh);
    }
  }
  return meshes;
}

function buildFloorAndCeiling(room: RoomInput, wallHeightFt: number): THREE.Mesh[] {
  const shape = new THREE.Shape(room.polygon.map(([x, y]) => new THREE.Vector2(x, y)));

  const floorGeometry = new THREE.ShapeGeometry(shape);
  floorGeometry.rotateX(-Math.PI / 2);
  const floor = new THREE.Mesh(floorGeometry, FLOOR_MATERIAL);
  floor.name = `floor:${room.name}`;

  const ceilingGeometry = new THREE.ShapeGeometry(shape);
  ceilingGeometry.rotateX(-Math.PI / 2);
  const ceiling = new THREE.Mesh(ceilingGeometry, CEILING_MATERIAL);
  ceiling.position.y = wallHeightFt;
  ceiling.name = `ceiling:${room.name}`;

  return [floor, ceiling];
}

function buildFurniturePlaceholder(placement: {
  room: string;
  object: string;
  position: Coord;
  rotation_deg: number;
}): THREE.Mesh {
  const dims = dimsForObject(placement.object);
  const geometry = new THREE.BoxGeometry(dims.width, dims.height, dims.depth);
  const mesh = new THREE.Mesh(geometry, FURNITURE_MATERIAL);
  mesh.position.copy(
    planToThree(placement.position[0], placement.position[1], dims.elevation + dims.height / 2),
  );
  mesh.rotation.y = bearingDegToThreeYRotation(placement.rotation_deg);
  mesh.name = `furniture:${placement.room}:${placement.object}`;
  return mesh;
}

export function buildScene(input: SceneInput): { scene: THREE.Scene; rooms: RoomMeta[] } {
  const scene = new THREE.Scene();
  const defaultWallHeight = input.wall_height_ft ?? DEFAULT_WALL_HEIGHT_FT;
  const openings = input.openings ?? [];
  const furniture = input.furniture ?? [];
  const rooms: RoomMeta[] = [];

  for (const room of input.rooms) {
    if (room.polygon.length < 3) {
      throw new Error(`room ${room.name} has fewer than 3 vertices`);
    }
    const wallHeightFt = room.wall_height_ft ?? defaultWallHeight;
    const roomOpenings = openings.filter((o) => o.room === room.name);

    const group = new THREE.Group();
    group.name = `room:${room.name}`;
    for (const mesh of buildWallsForRoom(room, wallHeightFt, roomOpenings)) group.add(mesh);
    for (const mesh of buildFloorAndCeiling(room, wallHeightFt)) group.add(mesh);
    scene.add(group);

    rooms.push({
      name: room.name,
      polygon: room.polygon,
      centroid: polygonCentroid(room.polygon),
      bounds: polygonBounds(room.polygon),
      wallHeightFt,
    });
  }

  const furnitureGroup = new THREE.Group();
  furnitureGroup.name = 'furniture';
  for (const placement of furniture) {
    furnitureGroup.add(buildFurniturePlaceholder(placement));
  }
  scene.add(furnitureGroup);

  const ambient = new THREE.AmbientLight(0xffffff, 0.6);
  const directional = new THREE.DirectionalLight(0xffffff, 0.8);
  directional.position.set(10, 20, 10);
  scene.add(ambient, directional);

  return { scene, rooms };
}
