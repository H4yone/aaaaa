import { Board, Building, GameState, Player, ResourceCounts, ResourceType, Road } from './types';

// ─── Building Costs ───────────────────────────────────────────────────────────

export const BASE_COSTS: Record<string, Partial<ResourceCounts>> = {
  road: { wood: 1, stone: 1 },
  village: { wood: 1, stone: 1, grain: 1, sheep: 1 },
  city: { grain: 2, iron: 3 },
  soldier: { sheep: 1, grain: 1, iron: 1 },
};

export function getBuildCost(
  type: 'road' | 'village' | 'city' | 'soldier',
  lord: Player['lord'],
): Partial<ResourceCounts> {
  const base = { ...BASE_COSTS[type] } as Partial<ResourceCounts>;

  if (type === 'road' && lord.type === 'architect') {
    delete base.stone;
  }
  if (type === 'city' && (lord.type === 'architect' || lord.type === 'warrior')) {
    base.iron = Math.max(0, (base.iron ?? 3) - 1);
  }
  if (type === 'soldier' && lord.type === 'warrior') {
    base.iron = Math.max(0, (base.iron ?? 1) - 1);
  }

  return base;
}

export function canAfford(res: ResourceCounts, cost: Partial<ResourceCounts>): boolean {
  for (const [k, v] of Object.entries(cost) as [ResourceType, number][]) {
    if ((res[k] ?? 0) < (v ?? 0)) return false;
  }
  return true;
}

export function deductCost(res: ResourceCounts, cost: Partial<ResourceCounts>): ResourceCounts {
  const r = { ...res };
  for (const [k, v] of Object.entries(cost) as [ResourceType, number][]) {
    r[k] = (r[k] ?? 0) - (v ?? 0);
  }
  return r;
}

// ─── Placement Validation ─────────────────────────────────────────────────────

export function isValidVillagePlacement(
  vertexId: number,
  buildings: Building[],
  roads: Road[],
  board: Board,
  playerId: number,
  requireRoad: boolean, // false during setup
): boolean {
  const vertex = board.vertices[vertexId];
  if (!vertex) return false;

  // Not already occupied
  if (buildings.some((b) => b.vertexId === vertexId)) return false;

  // Distance rule: no adjacent vertex may have a building
  for (const adjVid of vertex.adjacentVertexIds) {
    if (buildings.some((b) => b.vertexId === adjVid)) return false;
  }

  // Must be connected to own road (after setup)
  if (requireRoad) {
    const hasConnectedRoad = roads.some(
      (r) => r.playerId === playerId && board.edges[r.edgeId].vertexIds.includes(vertexId),
    );
    if (!hasConnectedRoad) return false;
  }

  return true;
}

export function isValidRoadPlacement(
  edgeId: number,
  roads: Road[],
  buildings: Building[],
  board: Board,
  playerId: number,
  setupAdjacentVertex?: number, // during setup: must be adjacent to last village
): boolean {
  const edge = board.edges[edgeId];
  if (!edge) return false;

  // Not already occupied
  if (roads.some((r) => r.edgeId === edgeId)) return false;

  if (setupAdjacentVertex !== undefined) {
    return edge.vertexIds.includes(setupAdjacentVertex);
  }

  // Must connect to own road or village
  const [vA, vB] = edge.vertexIds;

  for (const vid of [vA, vB]) {
    // Connected to own building
    if (buildings.some((b) => b.vertexId === vid && b.playerId === playerId)) return true;

    // Connected to own road via this vertex (and not blocked by enemy building)
    const enemyAtVertex = buildings.some((b) => b.vertexId === vid && b.playerId !== playerId);
    if (!enemyAtVertex) {
      for (const adjEid of board.vertices[vid].adjacentEdgeIds) {
        if (adjEid !== edgeId && roads.some((r) => r.edgeId === adjEid && r.playerId === playerId)) {
          return true;
        }
      }
    }
  }

  return false;
}

export function isValidCityUpgrade(
  vertexId: number,
  buildings: Building[],
  playerId: number,
): boolean {
  return buildings.some((b) => b.vertexId === vertexId && b.playerId === playerId && b.type === 'village');
}

export function validVillagePlacements(
  buildings: Building[],
  roads: Road[],
  board: Board,
  playerId: number,
  requireRoad: boolean,
): number[] {
  return board.vertices
    .map((v) => v.id)
    .filter((vid) => isValidVillagePlacement(vid, buildings, roads, board, playerId, requireRoad));
}

export function validRoadPlacements(
  roads: Road[],
  buildings: Building[],
  board: Board,
  playerId: number,
  setupAdjacentVertex?: number,
): number[] {
  return board.edges
    .map((e) => e.id)
    .filter((eid) => isValidRoadPlacement(eid, roads, buildings, board, playerId, setupAdjacentVertex));
}

export function validCityUpgrades(buildings: Building[], playerId: number): number[] {
  return buildings
    .filter((b) => b.playerId === playerId && b.type === 'village')
    .map((b) => b.vertexId);
}

// ─── Setup Order ──────────────────────────────────────────────────────────────

export function buildSetupOrder(playerCount: number): number[] {
  const forward = Array.from({ length: playerCount }, (_, i) => i);
  return [...forward, ...[...forward].reverse()];
}

// ─── Port Trade Rate ──────────────────────────────────────────────────────────

const PORT_RESOURCE_MAP: Record<string, ResourceType> = {
  'wood2:1': 'wood',
  'stone2:1': 'stone',
  'grain2:1': 'grain',
  'sheep2:1': 'sheep',
  'iron2:1': 'iron',
};

export function getTradeRate(
  resource: ResourceType,
  buildings: Building[],
  board: Board,
  playerId: number,
  isMerchant: boolean,
): number {
  let best = isMerchant ? 3 : 4;

  for (const building of buildings) {
    if (building.playerId !== playerId) continue;
    const vertex = board.vertices[building.vertexId];
    if (!vertex?.portType) continue;

    if (vertex.portType === '3:1') {
      best = Math.min(best, isMerchant ? 2 : 3);
    } else if (PORT_RESOURCE_MAP[vertex.portType] === resource) {
      best = Math.min(best, 2);
    }
  }

  return best;
}

// ─── Attack Validation ────────────────────────────────────────────────────────

export function validAttackTargets(
  buildings: Building[],
  board: Board,
  attackerId: number,
): Building[] {
  const attackerVerts = new Set<number>();

  // All vertices adjacent to attacker's buildings
  for (const b of buildings) {
    if (b.playerId !== attackerId) continue;
    for (const adjVid of board.vertices[b.vertexId].adjacentVertexIds) {
      attackerVerts.add(adjVid);
    }
  }

  // Enemy buildings on those vertices
  return buildings.filter(
    (b) => b.playerId !== attackerId && attackerVerts.has(b.vertexId),
  );
}
