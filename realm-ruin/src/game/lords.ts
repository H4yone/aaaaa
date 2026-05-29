import { Lord, LordType } from './types';

export const LORDS: Record<LordType, Lord> = {
  merchant: {
    type: 'merchant',
    name: 'Tüccar Lordu',
    description: 'Bankayla 3:1 takas (normal 4:1). Tüm limanlardan ek indirim.',
    emoji: '🪙',
  },
  warrior: {
    type: 'warrior',
    name: 'Savaşçı Lordu',
    description: '+2 ordu gücü, asker için 1 demir ucuz, saldırıda +1 yağma.',
    emoji: '⚔️',
  },
  architect: {
    type: 'architect',
    name: 'Mimar Lordu',
    description: 'Şehir 1 demir ucuz, yol için taş gerekmez.',
    emoji: '🏰',
  },
  healer: {
    type: 'healer',
    name: 'Şifacı Lordu',
    description: 'Veba/afet bağışıklığı, koyun toplarken +1 bonus.',
    emoji: '🌿',
  },
};

export const LORD_LIST: Lord[] = Object.values(LORDS);
