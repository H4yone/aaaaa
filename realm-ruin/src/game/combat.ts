import { Board, Building, Player, Road } from './types';

function d6(): number {
  return Math.floor(Math.random() * 6) + 1;
}

function wallBonus(vertexId: number, defenderId: number, roads: Road[], board: Board): number {
  const vertex = board.vertices[vertexId];
  let count = 0;
  for (const eid of vertex.adjacentEdgeIds) {
    if (roads.some((r) => r.edgeId === eid && r.playerId === defenderId)) count++;
  }
  return Math.min(2, count);
}

export interface CombatResult {
  attackRoll: number;
  defenseRoll: number;
  attackTotal: number;
  defenseTotal: number;
  attackerWins: boolean;
  log: string;
}

export function resolveCombat(
  attacker: Player,
  defender: Player,
  targetBuilding: Building,
  roads: Road[],
  board: Board,
): CombatResult {
  const attackDie = d6();
  const defenseDie = d6();

  const armyBonus = attacker.lord.type === 'warrior' ? 2 : 0;
  const wallBon = wallBonus(targetBuilding.vertexId, defender.id, roads, board);
  const buildingBonus = targetBuilding.type === 'city' ? 2 : 1;

  const attackTotal = attacker.soldiers + 1 + armyBonus + attackDie;
  const defenseTotal = buildingBonus + wallBon + 1 + defenseDie;

  const attackerWins = attackTotal > defenseTotal;

  const log =
    `⚔️ ${attacker.name} saldırdı! ` +
    `Saldırı: ${attackTotal} (${attacker.soldiers}+1+${armyBonus > 0 ? armyBonus + '+' : ''}🎲${attackDie}) ` +
    `Savunma: ${defenseTotal} (${buildingBonus}+duvar${wallBon}+1+🎲${defenseDie}) ` +
    `→ ${attackerWins ? '💥 Saldırı başarılı!' : '🛡️ Savunma tuttu!'}`;

  return { attackRoll: attackDie, defenseRoll: defenseDie, attackTotal, defenseTotal, attackerWins, log };
}

export function pillageAmount(attacker: Player): number {
  return attacker.lord.type === 'warrior' ? 2 : 1;
}
