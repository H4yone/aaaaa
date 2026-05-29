import { Board, Edge, HexTile, PortType, TileResource, Vertex } from './types';

const SQ3 = Math.sqrt(3);

// Pointy-top hex: vertices at angles 90°,30°,-30°,-90°,-150°,150° (in screen coords y-down)
const VERTEX_OFFSETS: [number, number][] = [
  [0, -1],           // 0: top
  [SQ3 / 2, -0.5],   // 1: top-right
  [SQ3 / 2, 0.5],    // 2: bottom-right
  [0, 1],            // 3: bottom
  [-SQ3 / 2, 0.5],   // 4: bottom-left
  [-SQ3 / 2, -0.5],  // 5: top-left
];

// 3-4-5-4-3 row layout
const ROW_COUNTS = [3, 4, 5, 4, 3];

function hexCenters(): { row: number; col: number; cx: number; cy: number }[] {
  const centers: { row: number; col: number; cx: number; cy: number }[] = [];
  for (let row = 0; row < ROW_COUNTS.length; row++) {
    const count = ROW_COUNTS[row];
    const cy = row * 1.5;
    const startX = ((5 - count) / 2) * SQ3;
    for (let col = 0; col < count; col++) {
      centers.push({ row, col, cx: startX + col * SQ3, cy });
    }
  }
  return centers;
}

function roundCoord(n: number): number {
  return Math.round(n * 10000) / 10000;
}

function vertexKey(x: number, y: number): string {
  return `${roundCoord(x)},${roundCoord(y)}`;
}

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// Pip count for probability display
export function pipCount(token: number): number {
  const pips: Record<number, number> = {
    2: 1, 12: 1, 3: 2, 11: 2, 4: 3, 10: 3, 5: 4, 9: 4, 6: 5, 8: 5,
  };
  return pips[token] ?? 0;
}

// Port positions: [hexId, vertexIndexA, vertexIndexB]
// Outer border vertex pairs for the 3-4-5-4-3 board, going clockwise from top-left
// These are coastal edges on the boundary hexes
const PORT_HEX_FACES: [number, number, number][] = [
  [0, 5, 0],   // top of hex 0
  [2, 0, 1],   // top-right of hex 2
  [6, 1, 2],   // right of hex 6
  [11, 2, 3],  // bottom-right of hex 11
  [18, 3, 4],  // bottom of hex 18
  [16, 3, 4],  // bottom of hex 16 — actually hex 16 and 17
  [16, 4, 5],  // bottom-left of hex 16
  [12, 4, 5],  // left of hex 12
  [7, 5, 0],   // top-left of hex 7
];

export function generateBoard(): Board {
  const centers = hexCenters();

  // ── Build vertex map ─────────────────────────────────────────────────────
  const vMap = new Map<string, number>(); // key -> vertex id
  const vertices: Vertex[] = [];
  const hexVerts: number[][] = []; // hexVerts[hexId] = [v0..v5]

  for (let hid = 0; hid < centers.length; hid++) {
    const { cx, cy } = centers[hid];
    const vids: number[] = [];

    for (const [dx, dy] of VERTEX_OFFSETS) {
      const vx = roundCoord(cx + dx);
      const vy = roundCoord(cy + dy);
      const key = vertexKey(vx, vy);

      if (!vMap.has(key)) {
        const vid = vertices.length;
        vMap.set(key, vid);
        vertices.push({
          id: vid,
          lx: vx,
          ly: vy,
          adjacentHexIds: [],
          adjacentVertexIds: [],
          adjacentEdgeIds: [],
          portType: null,
        });
      }

      const vid = vMap.get(key)!;
      vids.push(vid);
      if (!vertices[vid].adjacentHexIds.includes(hid)) {
        vertices[vid].adjacentHexIds.push(hid);
      }
    }

    hexVerts.push(vids);
  }

  // ── Build vertex adjacency ────────────────────────────────────────────────
  for (let hid = 0; hid < centers.length; hid++) {
    const vids = hexVerts[hid];
    for (let i = 0; i < 6; i++) {
      const a = vids[i];
      const b = vids[(i + 1) % 6];
      if (!vertices[a].adjacentVertexIds.includes(b)) vertices[a].adjacentVertexIds.push(b);
      if (!vertices[b].adjacentVertexIds.includes(a)) vertices[b].adjacentVertexIds.push(a);
    }
  }

  // ── Build edges ───────────────────────────────────────────────────────────
  const eMap = new Map<string, number>(); // key -> edge id
  const edges: Edge[] = [];

  for (let hid = 0; hid < centers.length; hid++) {
    const vids = hexVerts[hid];

    for (let i = 0; i < 6; i++) {
      const a = vids[i];
      const b = vids[(i + 1) % 6];
      const key = `${Math.min(a, b)},${Math.max(a, b)}`;

      if (!eMap.has(key)) {
        const eid = edges.length;
        eMap.set(key, eid);
        edges.push({ id: eid, vertexIds: [a, b], adjacentHexIds: [hid] });
      } else {
        const eid = eMap.get(key)!;
        if (!edges[eid].adjacentHexIds.includes(hid)) {
          edges[eid].adjacentHexIds.push(hid);
        }
      }

      const eid = eMap.get(key)!;
      if (!vertices[a].adjacentEdgeIds.includes(eid)) vertices[a].adjacentEdgeIds.push(eid);
      if (!vertices[b].adjacentEdgeIds.includes(eid)) vertices[b].adjacentEdgeIds.push(eid);
    }
  }

  // ── Resources & Tokens ───────────────────────────────────────────────────
  const resourceBag: TileResource[] = shuffle([
    'wood', 'wood', 'wood', 'wood',
    'stone', 'stone', 'stone',
    'grain', 'grain', 'grain', 'grain',
    'sheep', 'sheep', 'sheep', 'sheep',
    'iron', 'iron', 'iron',
    'desert',
  ]);

  const tokenBag = shuffle([2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]);

  let tokenIdx = 0;
  let desertHexId = 0;

  const hexes: HexTile[] = centers.map(({ row, col, cx, cy }, hid) => {
    const resource = resourceBag[hid];
    const isDesert = resource === 'desert';
    if (isDesert) desertHexId = hid;
    return {
      id: hid,
      resource,
      token: isDesert ? null : tokenBag[tokenIdx++],
      row,
      col,
      cx,
      cy,
      hasRobber: isDesert,
    };
  });

  // ── Ports ────────────────────────────────────────────────────────────────
  const portTypes: PortType[] = shuffle([
    '3:1', '3:1', '3:1', '3:1',
    'wood2:1', 'stone2:1', 'grain2:1', 'sheep2:1', 'iron2:1',
  ]);

  PORT_HEX_FACES.forEach(([hid, viA, viB], idx) => {
    if (hid >= hexVerts.length) return;
    const type = portTypes[idx] ?? '3:1';
    const va = hexVerts[hid][viA];
    const vb = hexVerts[hid][viB];
    if (va !== undefined) vertices[va].portType = type;
    if (vb !== undefined) vertices[vb].portType = type;
  });

  return { hexes, vertices, edges, desertHexId };
}

// Returns pixel positions scaled to board size
export function toPixel(
  lx: number,
  ly: number,
  hexSize: number,
  offsetX: number,
  offsetY: number,
): [number, number] {
  return [lx * hexSize + offsetX, ly * hexSize + offsetY];
}

// Board logical bounding box (used for scaling)
export const BOARD_LOGICAL_W = 4 * SQ3 + SQ3; // ~9.526
export const BOARD_LOGICAL_H = 4 * 1.5 + 2;   // 8
