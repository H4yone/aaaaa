import { Board, Building, GameState, Player, ResourceCounts, ResourceType, Road, TradeOffer } from '../game/types';
import { canAfford, getBuildCost, getTradeRate, validAttackTargets, validCityUpgrades, validRoadPlacements, validVillagePlacements } from '../game/rules';
import { totalResources } from '../game/resources';
import { pipCount } from '../game/board';
import { totalVPs } from '../game/scoring';

// Utility value: how much a resource is worth to a player given their needs
function resourceValue(res: ResourceType, player: Player, buildings: Building[]): number {
  const village = getBuildCost('village', player.lord);
  const city = getBuildCost('city', player.lord);
  const road = getBuildCost('road', player.lord);

  const haveVillages = buildings.filter((b) => b.playerId === player.id && b.type === 'village').length;
  const haveCities = buildings.filter((b) => b.playerId === player.id && b.type === 'city').length;

  let value = 0;
  // High value if needed for priority builds
  if (haveVillages > haveCities && city[res]) value += (city[res]! * 3);
  if (village[res]) value += (village[res]! * 2);
  if (road[res]) value += road[res]!;

  // Reduce value if already have surplus
  const current = player.resources[res];
  if (current > 3) value = Math.max(0, value - (current - 3) * 2);

  return value;
}

export function aiEvalTradeOffer(
  offer: TradeOffer,
  player: Player,
  buildings: Building[],
): boolean {
  // Sum utility of received vs given
  let gainValue = 0;
  let lossValue = 0;

  for (const [r, amount] of Object.entries(offer.receive) as [ResourceType, number][]) {
    gainValue += resourceValue(r, player, buildings) * (amount ?? 0);
  }
  for (const [r, amount] of Object.entries(offer.give) as [ResourceType, number][]) {
    lossValue += resourceValue(r, player, buildings) * (amount ?? 0);
    // Also check affordability
    if ((player.resources[r] ?? 0) < (amount ?? 0)) return false;
  }

  return gainValue > lossValue;
}

// AI generates a trade offer to the human player
export function aiGenerateOffer(
  ai: Player,
  humanId: number,
  buildings: Building[],
): TradeOffer | null {
  const ALL_RES: ResourceType[] = ['wood', 'stone', 'grain', 'sheep', 'iron'];
  const surplus: ResourceType[] = ALL_RES.filter((r) => ai.resources[r] >= 3);
  const wanted: ResourceType[] = ALL_RES.filter((r) => ai.resources[r] === 0);

  if (surplus.length === 0 || wanted.length === 0) return null;

  const give: Partial<ResourceCounts> = { [surplus[0]]: 2 };
  const receive: Partial<ResourceCounts> = { [wanted[0]]: 1 };

  return { fromPlayerId: ai.id, toPlayerId: humanId, give, receive };
}

// Score a vertex for initial placement
function scorePlacement(vertexId: number, board: Board, buildings: Building[]): number {
  // Already taken
  if (buildings.some((b) => b.vertexId === vertexId)) return -1;

  // Distance rule check
  const vertex = board.vertices[vertexId];
  for (const adjVid of vertex.adjacentVertexIds) {
    if (buildings.some((b) => b.vertexId === adjVid)) return -1;
  }

  let score = 0;
  const seenResources = new Set<string>();

  for (const hexId of vertex.adjacentHexIds) {
    const hex = board.hexes[hexId];
    if (hex.resource === 'desert' || !hex.token) continue;
    score += pipCount(hex.token);
    seenResources.add(hex.resource);
  }

  // Diversity bonus
  score += seenResources.size * 2;

  // Port bonus
  if (vertex.portType) score += 4;

  return score;
}

export function aiBestPlacement(board: Board, buildings: Building[]): number | null {
  let best = -1;
  let bestScore = -1;

  for (const vertex of board.vertices) {
    const s = scorePlacement(vertex.id, board, buildings);
    if (s > bestScore) {
      bestScore = s;
      best = vertex.id;
    }
  }

  return best >= 0 ? best : null;
}

export function aiBestRoad(
  board: Board,
  roads: Road[],
  buildings: Building[],
  playerId: number,
  setupAdjacentVertex?: number,
): number | null {
  const options = validRoadPlacements(roads, buildings, board, playerId, setupAdjacentVertex);
  if (options.length === 0) return null;

  // Pick road that leads toward high-scoring vertices
  let best = options[0];
  let bestScore = 0;

  for (const eid of options) {
    const edge = board.edges[eid];
    let score = 0;
    for (const vid of edge.vertexIds) {
      score += scorePlacement(vid, board, buildings);
    }
    if (score > bestScore) {
      bestScore = score;
      best = eid;
    }
  }

  return best;
}

// Decide build action during AI's turn
export interface AIBuildAction {
  type: 'city' | 'village' | 'road' | 'soldier' | 'trade' | null;
  vertexId?: number;
  edgeId?: number;
  tradeResource?: ResourceType;
  tradeFor?: ResourceType;
}

export function aiDecideBuild(
  ai: Player,
  board: Board,
  buildings: Building[],
  roads: Road[],
  allPlayers: Player[],
): AIBuildAction {
  const res = ai.resources;

  // 1. Try city upgrade
  const cityCost = getBuildCost('city', ai.lord);
  const cityTargets = validCityUpgrades(buildings, ai.id);
  if (cityTargets.length > 0 && canAfford(res, cityCost)) {
    return { type: 'city', vertexId: cityTargets[0] };
  }

  // 2. Try new village
  const villageCost = getBuildCost('village', ai.lord);
  const villageTargets = validVillagePlacements(buildings, roads, board, ai.id, true);
  if (villageTargets.length > 0 && canAfford(res, villageCost)) {
    const best = aiBestVillageFromValid(villageTargets, board);
    if (best !== null) return { type: 'village', vertexId: best };
  }

  // 3. Try road if can expand
  const roadCost = getBuildCost('road', ai.lord);
  if (canAfford(res, roadCost) && villageTargets.length === 0) {
    const roadTarget = aiBestRoad(board, roads, buildings, ai.id);
    if (roadTarget !== null) return { type: 'road', edgeId: roadTarget };
  }

  // 4. Try soldier
  const soldierCost = getBuildCost('soldier', ai.lord);
  if (canAfford(res, soldierCost) && ai.soldiers < 5) {
    return { type: 'soldier' };
  }

  // 5. Try bank trade to get what we need
  const ALL_RES: ResourceType[] = ['wood', 'stone', 'grain', 'sheep', 'iron'];
  const targets: Array<[string, Partial<ResourceCounts>]> = [
    ['city', cityCost],
    ['village', villageCost],
    ['road', roadCost],
    ['soldier', soldierCost],
  ];

  for (const [, cost] of targets) {
    for (const [needed, amt] of Object.entries(cost) as [ResourceType, number][]) {
      if ((res[needed] ?? 0) >= (amt ?? 0)) continue;
      // Find surplus to trade
      const rate = getTradeRate(needed, buildings, board, ai.id, ai.lord.type === 'merchant');
      for (const surplus of ALL_RES) {
        if (surplus === needed) continue;
        if ((res[surplus] ?? 0) >= rate) {
          return { type: 'trade', tradeResource: surplus, tradeFor: needed };
        }
      }
    }
  }

  return { type: null };
}

function aiBestVillageFromValid(vertexIds: number[], board: Board): number | null {
  let best = -1;
  let bestScore = -Infinity;

  for (const vid of vertexIds) {
    const vertex = board.vertices[vid];
    let score = 0;
    for (const hexId of vertex.adjacentHexIds) {
      const hex = board.hexes[hexId];
      if (hex.resource !== 'desert' && hex.token) {
        score += pipCount(hex.token);
      }
    }
    if (vertex.portType) score += 4;
    if (score > bestScore) {
      bestScore = score;
      best = vid;
    }
  }

  return best >= 0 ? best : null;
}

// AI chooses robber placement: hex adjacent to highest VP enemy, not own hex
export function aiChooseRobber(
  aiId: number,
  board: Board,
  buildings: Building[],
  allPlayers: Player[],
): { hexId: number; stealFromId: number | null } {
  let bestHexId = board.desertHexId;
  let stealFrom: number | null = null;
  let bestScore = -1;

  for (const hex of board.hexes) {
    if (hex.id === board.desertHexId) continue;

    // Don't block own buildings
    const ownBuilding = buildings.some(
      (b) => b.playerId === aiId && board.vertices[b.vertexId].adjacentHexIds.includes(hex.id),
    );
    if (ownBuilding) continue;

    // Score by adjacent enemy VP
    let score = 0;
    let target: number | null = null;
    let targetVP = 0;

    for (const b of buildings) {
      if (b.playerId === aiId) continue;
      if (!board.vertices[b.vertexId].adjacentHexIds.includes(hex.id)) continue;
      const vp = totalVPs(buildings, allPlayers[b.playerId]);
      if (vp > targetVP) {
        targetVP = vp;
        target = b.playerId;
      }
      score += vp + (hex.token ? pipCount(hex.token) : 0);
    }

    if (score > bestScore) {
      bestScore = score;
      bestHexId = hex.id;
      stealFrom = target;
    }
  }

  return { hexId: bestHexId, stealFromId: stealFrom };
}
