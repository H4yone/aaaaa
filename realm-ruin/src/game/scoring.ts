import { Board, Building, GameState, Player, Road } from './types';

export function buildingVPs(buildings: Building[], playerId: number): number {
  let vp = 0;
  for (const b of buildings) {
    if (b.playerId !== playerId) continue;
    vp += b.type === 'city' ? 2 : 1;
  }
  return vp;
}

export function totalVPs(buildings: Building[], player: Player): number {
  let vp = buildingVPs(buildings, player.id);
  if (player.hasLargestArmy) vp += 2;
  if (player.hasLongestRoad) vp += 2;
  return vp;
}

// ─── Longest Road (DFS) ───────────────────────────────────────────────────────

export function longestRoadLength(
  playerId: number,
  roads: Road[],
  buildings: Building[],
  board: Board,
): number {
  const playerEdges = new Set(
    roads.filter((r) => r.playerId === playerId).map((r) => r.edgeId),
  );
  if (playerEdges.size === 0) return 0;

  let best = 0;

  function dfs(vertexId: number, visitedEdges: Set<number>): void {
    const vertex = board.vertices[vertexId];
    for (const eid of vertex.adjacentEdgeIds) {
      if (!playerEdges.has(eid) || visitedEdges.has(eid)) continue;

      // Check if enemy building blocks this vertex (breaks road)
      const edge = board.edges[eid];
      const otherVertexId = edge.vertexIds[0] === vertexId ? edge.vertexIds[1] : edge.vertexIds[0];
      const enemyBlock = buildings.some(
        (b) => b.vertexId === otherVertexId && b.playerId !== playerId,
      );
      if (enemyBlock) continue;

      visitedEdges.add(eid);
      if (visitedEdges.size > best) best = visitedEdges.size;
      dfs(otherVertexId, visitedEdges);
      visitedEdges.delete(eid);
    }
  }

  // Start DFS from each player road vertex
  for (const eid of playerEdges) {
    const edge = board.edges[eid];
    for (const vid of edge.vertexIds) {
      const visited = new Set<number>();
      visited.add(eid);
      if (visited.size > best) best = visited.size;
      dfs(vid, visited);
    }
  }

  return best;
}

// ─── Update Special Awards ────────────────────────────────────────────────────

export function updateSpecialAwards(
  players: Player[],
  buildings: Building[],
  roads: Road[],
  board: Board,
): Player[] {
  // Largest Army
  let maxArmy = 2; // minimum 3 soldiers to qualify (stored as 3-1=2 minimum to beat)
  let armyHolder = players.findIndex((p) => p.hasLargestArmy);

  for (const p of players) {
    if (p.soldiers > maxArmy) {
      maxArmy = p.soldiers;
    }
  }

  let newArmyHolder = -1;
  if (maxArmy >= 3) {
    // Current holder keeps it on tie
    if (armyHolder >= 0 && players[armyHolder].soldiers === maxArmy) {
      newArmyHolder = armyHolder;
    } else {
      newArmyHolder = players.findIndex((p) => p.soldiers === maxArmy);
    }
  }

  // Longest Road
  const roadLengths = players.map((p) => longestRoadLength(p.id, roads, buildings, board));
  let maxRoad = 4; // minimum 5 to qualify
  let roadHolder = players.findIndex((p) => p.hasLongestRoad);

  for (const len of roadLengths) {
    if (len > maxRoad) maxRoad = len;
  }

  let newRoadHolder = -1;
  if (maxRoad >= 5) {
    if (roadHolder >= 0 && roadLengths[roadHolder] === maxRoad) {
      newRoadHolder = roadHolder;
    } else {
      newRoadHolder = roadLengths.findIndex((l) => l === maxRoad);
    }
  }

  return players.map((p, i) => ({
    ...p,
    hasLargestArmy: i === newArmyHolder,
    hasLongestRoad: i === newRoadHolder,
  }));
}

export function checkWinner(
  players: Player[],
  buildings: Building[],
): number | null {
  for (const p of players) {
    if (totalVPs(buildings, p) >= 10) return p.id;
  }
  return null;
}
