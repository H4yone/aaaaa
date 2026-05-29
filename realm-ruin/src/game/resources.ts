import { Board, Building, HexTile, Player, ResourceCounts, ResourceType } from './types';

export const ZERO_RESOURCES: ResourceCounts = {
  wood: 0, stone: 0, grain: 0, sheep: 0, iron: 0,
};

export function emptyResources(): ResourceCounts {
  return { ...ZERO_RESOURCES };
}

export function totalResources(res: ResourceCounts): number {
  return Object.values(res).reduce((a, b) => a + b, 0);
}

export function addResources(a: ResourceCounts, b: Partial<ResourceCounts>): ResourceCounts {
  const result = { ...a };
  for (const [k, v] of Object.entries(b) as [ResourceType, number][]) {
    result[k] = (result[k] ?? 0) + (v ?? 0);
  }
  return result;
}

export function subtractResources(a: ResourceCounts, b: Partial<ResourceCounts>): ResourceCounts {
  const result = { ...a };
  for (const [k, v] of Object.entries(b) as [ResourceType, number][]) {
    result[k] = Math.max(0, (result[k] ?? 0) - (v ?? 0));
  }
  return result;
}

// Returns what each player gains from a dice roll
export function produceResources(
  diceTotal: number,
  board: Board,
  buildings: Building[],
  players: Player[],
): ResourceCounts[] {
  const gains: ResourceCounts[] = players.map(() => emptyResources());

  const productiveHexes = board.hexes.filter(
    (h) => h.token === diceTotal && !h.hasRobber && h.resource !== 'desert',
  );

  for (const hex of productiveHexes) {
    for (const building of buildings) {
      const vertex = board.vertices[building.vertexId];
      if (!vertex.adjacentHexIds.includes(hex.id)) continue;

      const amount = building.type === 'city' ? 2 : 1;
      const pid = building.playerId;
      const resource = hex.resource as ResourceType;

      // Healer lord gets +1 sheep
      const bonus =
        players[pid].lord.type === 'healer' && resource === 'sheep' ? 1 : 0;

      gains[pid][resource] = (gains[pid][resource] ?? 0) + amount + bonus;
    }
  }

  return gains;
}

// Produce starting resources (second village in setup)
export function startingResources(
  vertexId: number,
  board: Board,
  lord: Player['lord'],
): ResourceCounts {
  const result = emptyResources();
  const vertex = board.vertices[vertexId];

  for (const hexId of vertex.adjacentHexIds) {
    const hex = board.hexes[hexId];
    if (hex.resource === 'desert') continue;
    const resource = hex.resource as ResourceType;
    const bonus = lord.type === 'healer' && resource === 'sheep' ? 1 : 0;
    result[resource] = (result[resource] ?? 0) + 1 + bonus;
  }

  return result;
}

// Returns half-rounded-down (for robber 7 discard)
export function halfDiscard(res: ResourceCounts): ResourceCounts {
  const total = totalResources(res);
  let toDiscard = Math.floor(total / 2);
  const result = { ...res };

  const order: ResourceType[] = ['wood', 'stone', 'grain', 'sheep', 'iron'];
  for (const r of order) {
    if (toDiscard <= 0) break;
    const take = Math.min(result[r], toDiscard);
    result[r] -= take;
    toDiscard -= take;
  }

  return result;
}
