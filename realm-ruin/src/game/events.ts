import { GameEvent, GameEventType, Player, ResourceCounts, ResourceType } from './types';
import { emptyResources } from './resources';

const EVENTS: GameEvent[] = [
  {
    type: 'plague',
    emoji: '☠️',
    title: 'Veba!',
    description: 'Tüm oyuncular kaynaklarının yarısını kaybetti.',
  },
  {
    type: 'drought',
    emoji: '🌵',
    title: 'Kuraklık!',
    description: 'Bu tur tahıl üretimi yok.',
  },
  {
    type: 'harvest',
    emoji: '🌾',
    title: 'Bereket!',
    description: 'Herkes 1 tahıl kazandı.',
  },
  {
    type: 'dragon',
    emoji: '🐉',
    title: 'Ejderha Saldırısı!',
    description: 'Rastgele bir oyuncu demir/taş kaybetti.',
  },
  {
    type: 'crusade',
    emoji: '✝️',
    title: 'Haçlı Seferi!',
    description: 'Herkes 1 asker kazandı.',
  },
  {
    type: 'caravan',
    emoji: '🐫',
    title: 'Ticaret Kervanı!',
    description: 'Herkes rastgele 1 kaynak kazandı.',
  },
];

export function maybeRollEvent(): GameEvent | null {
  if (Math.random() > 0.2) return null;
  return EVENTS[Math.floor(Math.random() * EVENTS.length)];
}

const ALL_RESOURCES: ResourceType[] = ['wood', 'stone', 'grain', 'sheep', 'iron'];

export function applyEvent(
  event: GameEvent,
  players: Player[],
): { newResources: ResourceCounts[]; soldiers: number[] } {
  const newResources = players.map((p) => ({ ...p.resources }));
  const soldiers = players.map((p) => p.soldiers);

  switch (event.type) {
    case 'plague':
      for (let i = 0; i < players.length; i++) {
        if (players[i].lord.type === 'healer') continue;
        for (const r of ALL_RESOURCES) {
          newResources[i][r] = Math.floor(newResources[i][r] / 2);
        }
      }
      break;

    case 'harvest':
      for (let i = 0; i < players.length; i++) {
        newResources[i].grain += 1;
      }
      break;

    case 'dragon': {
      const targetIdx = Math.floor(Math.random() * players.length);
      if (players[targetIdx].lord.type !== 'healer') {
        if (newResources[targetIdx].iron > 0) newResources[targetIdx].iron -= 1;
        else if (newResources[targetIdx].stone > 0) newResources[targetIdx].stone -= 1;
      }
      break;
    }

    case 'crusade':
      for (let i = 0; i < players.length; i++) {
        soldiers[i] += 1;
      }
      break;

    case 'caravan': {
      const r = ALL_RESOURCES[Math.floor(Math.random() * ALL_RESOURCES.length)];
      for (let i = 0; i < players.length; i++) {
        newResources[i][r] += 1;
      }
      break;
    }

    // drought is handled separately in resource production (skip grain)
  }

  return { newResources, soldiers };
}
