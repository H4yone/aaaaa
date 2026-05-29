import { create } from 'zustand';
import { generateBoard } from '../game/board';
import { LORD_LIST, LORDS } from '../game/lords';
import { emptyResources, halfDiscard, produceResources, startingResources, totalResources } from '../game/resources';
import { buildSetupOrder, canAfford, deductCost, getBuildCost, getTradeRate, isValidRoadPlacement, isValidVillagePlacement, validAttackTargets } from '../game/rules';
import { applyEvent, maybeRollEvent } from '../game/events';
import { checkWinner, totalVPs, updateSpecialAwards } from '../game/scoring';
import { aiBestPlacement, aiBestRoad, aiChooseRobber, aiDecideBuild, aiEvalTradeOffer, aiGenerateOffer } from '../ai/ai';
import { clearSave, loadGame, saveGame } from './persistence';
import {
  Building, GameState, LogCategory, LogEntry, Player, ResourceCounts, ResourceType, Road, TradeOffer
} from '../game/types';

const COLORS = ['#c0392b', '#2980b9', '#27ae60', '#8e44ad'];
const AI_NAMES = ['Lord Aldric', 'Lady Mira', 'Baron Vex'];

function log(
  state: GameState,
  message: string,
  category: LogCategory,
): GameState {
  const entry: LogEntry = {
    id: state.log.length,
    message,
    category,
    turn: state.turnNumber,
  };
  return { ...state, log: [entry, ...state.log].slice(0, 100) };
}

function rollDie(): number {
  return Math.floor(Math.random() * 6) + 1;
}

// ─────────────────────────────────────────────────────────────────────────────

interface GameStore {
  state: GameState | null;
  isSaveAvailable: boolean;

  initGame: (playerCount: number, lordChoices: number[]) => void;
  loadSavedGame: () => Promise<void>;
  checkSave: () => Promise<void>;

  // Setup phase
  placeSetupVillage: (vertexId: number) => void;
  placeSetupRoad: (edgeId: number) => void;

  // Gameplay
  rollDice: () => void;
  moveRobber: (hexId: number) => void;
  stealResource: (targetPlayerId: number) => void;
  buildVillage: (vertexId: number) => void;
  buildRoad: (edgeId: number) => void;
  buildCity: (vertexId: number) => void;
  buildSoldier: () => void;
  bankTrade: (give: ResourceType, receive: ResourceType) => void;
  offerTrade: (offer: TradeOffer) => void;
  respondToTrade: (accept: boolean) => void;
  attackBuilding: (targetVertexId: number) => void;
  endTurn: () => void;
}

export const useGameStore = create<GameStore>((set, get) => ({
  state: null,
  isSaveAvailable: false,

  checkSave: async () => {
    const { hasSave } = await import('./persistence');
    const available = await hasSave();
    set({ isSaveAvailable: available });
  },

  loadSavedGame: async () => {
    const saved = await loadGame();
    if (saved) set({ state: saved });
  },

  initGame: (playerCount: number, lordChoices: number[]) => {
    const board = generateBoard();

    const players: Player[] = Array.from({ length: playerCount }, (_, i) => ({
      id: i,
      name: i === 0 ? 'Sen' : AI_NAMES[i - 1],
      lord: LORDS[LORD_LIST[lordChoices[i]].type],
      color: COLORS[i],
      resources: emptyResources(),
      soldiers: 0,
      hasLargestArmy: false,
      hasLongestRoad: false,
      isAI: i !== 0,
    }));

    const setupOrder = buildSetupOrder(playerCount);

    const initial: GameState = {
      board,
      players,
      buildings: [],
      roads: [],
      phase: 'setup',
      setup: {
        order: setupOrder,
        step: 0,
        round: 1,
        pendingRoad: false,
        lastVillageId: null,
      },
      currentPlayerIndex: setupOrder[0],
      actionPhase: 'preroll',
      turnNumber: 1,
      diceValues: null,
      lastEvent: null,
      pendingTradeOffer: null,
      pendingRobberSteal: null,
      log: [],
      winner: null,
      hasAttackedThisTurn: false,
    };

    const stateWithLog = log(initial, '⚔️ Realm & Ruin başladı! İlk köyünü yerleştir.', 'system');
    set({ state: stateWithLog, isSaveAvailable: false });

    // If first player is AI, trigger their setup turn
    if (players[setupOrder[0]].isAI) {
      setTimeout(() => get().placeSetupVillage(-1), 500);
    }
  },

  placeSetupVillage: (vertexId: number) => {
    const gs = get().state;
    if (!gs || gs.phase !== 'setup' || gs.setup.pendingRoad) return;

    let vid = vertexId;
    const pid = gs.currentPlayerIndex;
    const isAI = gs.players[pid].isAI;

    if (isAI) {
      const best = aiBestPlacement(gs.board, gs.buildings);
      if (best === null) return;
      vid = best;
    }

    if (!isValidVillagePlacement(vid, gs.buildings, gs.roads, gs.board, pid, false)) return;

    const newBuildings: Building[] = [...gs.buildings, { vertexId: vid, playerId: pid, type: 'village' }];

    let newPlayers = [...gs.players];
    // Second round: give starting resources
    if (gs.setup.round === 2) {
      const gained = startingResources(vid, gs.board, gs.players[pid].lord);
      const resLog = Object.entries(gained)
        .filter(([, v]) => v > 0)
        .map(([k, v]) => `${v}x ${k}`)
        .join(', ');
      newPlayers = newPlayers.map((p, i) =>
        i === pid
          ? { ...p, resources: Object.fromEntries(Object.entries(p.resources).map(([k, v]) => [k, v + (gained[k as ResourceType] ?? 0)])) as ResourceCounts }
          : p,
      );
      if (resLog) {
        let s = log({ ...gs, players: newPlayers, buildings: newBuildings }, `🏘️ ${gs.players[pid].name} köy kurdu (+${resLog})`, 'build');
        set({ state: { ...s, setup: { ...s.setup, pendingRoad: true, lastVillageId: vid } } });
        if (isAI) setTimeout(() => get().placeSetupRoad(-1), 600);
        return;
      }
    }

    let s = log({ ...gs, buildings: newBuildings }, `🏘️ ${gs.players[pid].name} köy kurdu`, 'build');
    s = { ...s, setup: { ...s.setup, pendingRoad: true, lastVillageId: vid } };
    set({ state: s });
    if (isAI) setTimeout(() => get().placeSetupRoad(-1), 600);
  },

  placeSetupRoad: (edgeId: number) => {
    const gs = get().state;
    if (!gs || gs.phase !== 'setup' || !gs.setup.pendingRoad) return;

    const pid = gs.currentPlayerIndex;
    const isAI = gs.players[pid].isAI;
    let eid = edgeId;

    if (isAI) {
      const best = aiBestRoad(gs.board, gs.roads, gs.buildings, pid, gs.setup.lastVillageId ?? undefined);
      if (best === null) return;
      eid = best;
    }

    if (!isValidRoadPlacement(eid, gs.roads, gs.buildings, gs.board, pid, gs.setup.lastVillageId ?? undefined)) return;

    const newRoads: Road[] = [...gs.roads, { edgeId: eid, playerId: pid }];
    let s = log({ ...gs, roads: newRoads }, `🛤️ ${gs.players[pid].name} yol kurdu`, 'build');

    // Advance setup step
    const nextStep = gs.setup.step + 1;
    const totalSteps = gs.setup.order.length;

    if (nextStep >= totalSteps) {
      // Setup complete
      s = log(
        { ...s, phase: 'playing', setup: { ...s.setup, pendingRoad: false, step: nextStep } },
        '🎮 Hazırlık tamamlandı! Oyun başlıyor.',
        'system',
      );
      s = { ...s, currentPlayerIndex: 0, actionPhase: 'preroll', turnNumber: 1 };
      set({ state: s });
      saveGame(s);
      return;
    }

    const nextPlayerIdx = gs.setup.order[nextStep];
    const isSecondRound = nextStep >= gs.players.length;

    s = {
      ...s,
      currentPlayerIndex: nextPlayerIdx,
      setup: {
        ...s.setup,
        step: nextStep,
        round: isSecondRound ? 2 : 1,
        pendingRoad: false,
        lastVillageId: null,
      },
    };

    set({ state: s });

    if (gs.players[nextPlayerIdx].isAI) {
      setTimeout(() => get().placeSetupVillage(-1), 700);
    }
  },

  rollDice: () => {
    const gs = get().state;
    if (!gs || gs.phase !== 'playing' || gs.actionPhase !== 'preroll') return;

    const d1 = rollDie();
    const d2 = rollDie();
    const total = d1 + d2;

    let s: GameState = { ...gs, diceValues: [d1, d2] };
    s = log(s, `🎲 ${gs.players[gs.currentPlayerIndex].name} zar attı: ${d1}+${d2}=${total}`, 'dice');

    // Random event check
    const event = maybeRollEvent();
    if (event) {
      s = log(s, `${event.emoji} ${event.title} — ${event.description}`, 'event');
      const { newResources, soldiers } = applyEvent(event, s.players);
      s = {
        ...s,
        lastEvent: event,
        players: s.players.map((p, i) => ({
          ...p,
          resources: newResources[i],
          soldiers: soldiers[i],
        })),
      };
    }

    if (total === 7) {
      // Discard excess
      let newPlayers = s.players.map((p) => {
        if (p.lord.type === 'healer') return p;
        if (totalResources(p.resources) <= 7) return p;
        return { ...p, resources: halfDiscard(p.resources) };
      });
      s = log({ ...s, players: newPlayers }, '🦹 7 atıldı! 7\'den fazla kaynağı olan oyuncular yarısını kaybetti.', 'event');
      s = { ...s, actionPhase: 'robber' };

      if (gs.players[gs.currentPlayerIndex].isAI) {
        const { hexId, stealFromId: stealFrom } = aiChooseRobber(gs.currentPlayerIndex, gs.board, gs.buildings, newPlayers);
        s = applyRobberMove(s, hexId, stealFrom);
      }
    } else {
      // Produce resources (skip grain on drought)
      const droughtActive = s.lastEvent?.type === 'drought';
      let gains = produceResources(total, s.board, s.buildings, s.players);

      if (droughtActive) {
        gains = gains.map((g) => ({ ...g, grain: 0 }));
      }

      const newPlayers = s.players.map((p, i) => ({
        ...p,
        resources: Object.fromEntries(
          Object.entries(p.resources).map(([k, v]) => [k, v + (gains[i][k as ResourceType] ?? 0)]),
        ) as ResourceCounts,
      }));

      const totalGain = gains.reduce((sum, g) => sum + totalResources(g as ResourceCounts), 0);
      if (totalGain > 0) {
        s = log({ ...s, players: newPlayers }, `📦 Kaynaklar üretildi (toplam ${totalGain}).`, 'dice');
      }
      s = { ...s, actionPhase: 'postroll' };
    }

    set({ state: s });
    saveGame(s);
  },

  moveRobber: (hexId: number) => {
    const gs = get().state;
    if (!gs || gs.actionPhase !== 'robber') return;

    const newHexes = gs.board.hexes.map((h) => ({
      ...h,
      hasRobber: h.id === hexId,
    }));

    let s: GameState = {
      ...gs,
      board: { ...gs.board, hexes: newHexes },
    };
    s = log(s, `🦹 Haydut taşındı!`, 'event');

    // Find stealable players (adjacent to new robber hex, not self)
    const vertex = gs.board.vertices;
    const adjacentPlayers = new Set<number>();
    for (const v of vertex) {
      if (v.adjacentHexIds.includes(hexId)) {
        for (const b of gs.buildings) {
          if (b.vertexId === v.id && b.playerId !== gs.currentPlayerIndex) {
            if (totalResources(gs.players[b.playerId].resources) > 0) {
              adjacentPlayers.add(b.playerId);
            }
          }
        }
      }
    }

    if (adjacentPlayers.size === 1) {
      const target = [...adjacentPlayers][0];
      s = { ...s, actionPhase: 'postroll', pendingRobberSteal: target };
    } else if (adjacentPlayers.size > 1) {
      s = { ...s, actionPhase: 'postroll', pendingRobberSteal: -1 }; // multiple options, player chooses
    } else {
      s = { ...s, actionPhase: 'postroll', pendingRobberSteal: null };
    }

    set({ state: s });
    saveGame(s);
  },

  stealResource: (targetPlayerId: number) => {
    const gs = get().state;
    if (!gs) return;

    const target = gs.players[targetPlayerId];
    const resources = Object.entries(target.resources)
      .filter(([, v]) => v > 0)
      .map(([k]) => k as ResourceType);

    if (resources.length === 0) {
      set({ state: { ...gs, pendingRobberSteal: null } });
      return;
    }

    const stolen = resources[Math.floor(Math.random() * resources.length)];
    const newPlayers = gs.players.map((p, i) => {
      if (i === targetPlayerId) {
        return { ...p, resources: { ...p.resources, [stolen]: Math.max(0, p.resources[stolen] - 1) } };
      }
      if (i === gs.currentPlayerIndex) {
        return { ...p, resources: { ...p.resources, [stolen]: p.resources[stolen] + 1 } };
      }
      return p;
    });

    let s = log({ ...gs, players: newPlayers, pendingRobberSteal: null }, `🤜 ${gs.players[gs.currentPlayerIndex].name} ${target.name}'dan 1 kaynak çaldı!`, 'combat');
    set({ state: s });
    saveGame(s);
  },

  buildVillage: (vertexId: number) => {
    const gs = get().state;
    if (!gs || gs.phase !== 'playing' || gs.actionPhase !== 'postroll') return;

    const pid = gs.currentPlayerIndex;
    const player = gs.players[pid];
    const cost = getBuildCost('village', player.lord);

    if (!canAfford(player.resources, cost)) return;
    if (!isValidVillagePlacement(vertexId, gs.buildings, gs.roads, gs.board, pid, true)) return;

    const newRes = deductCost(player.resources, cost);
    const newBuildings: Building[] = [...gs.buildings, { vertexId, playerId: pid, type: 'village' }];
    let newPlayers = gs.players.map((p, i) => (i === pid ? { ...p, resources: newRes } : p));
    newPlayers = updateSpecialAwards(newPlayers, newBuildings, gs.roads, gs.board);

    let s = log({ ...gs, players: newPlayers, buildings: newBuildings }, `🏘️ ${player.name} köy kurdu! (+1 ZP)`, 'build');

    const winner = checkWinner(s.players, s.buildings);
    if (winner !== null) s = { ...s, phase: 'ended', winner };

    set({ state: s });
    saveGame(s);
  },

  buildRoad: (edgeId: number) => {
    const gs = get().state;
    if (!gs || gs.phase !== 'playing' || gs.actionPhase !== 'postroll') return;

    const pid = gs.currentPlayerIndex;
    const player = gs.players[pid];
    const cost = getBuildCost('road', player.lord);

    if (!canAfford(player.resources, cost)) return;
    if (!isValidRoadPlacement(edgeId, gs.roads, gs.buildings, gs.board, pid)) return;

    const newRes = deductCost(player.resources, cost);
    const newRoads: Road[] = [...gs.roads, { edgeId, playerId: pid }];
    let newPlayers = gs.players.map((p, i) => (i === pid ? { ...p, resources: newRes } : p));
    newPlayers = updateSpecialAwards(newPlayers, gs.buildings, newRoads, gs.board);

    let s = log({ ...gs, players: newPlayers, roads: newRoads }, `🛤️ ${player.name} yol inşa etti.`, 'build');

    const winner = checkWinner(s.players, s.buildings);
    if (winner !== null) s = { ...s, phase: 'ended', winner };

    set({ state: s });
    saveGame(s);
  },

  buildCity: (vertexId: number) => {
    const gs = get().state;
    if (!gs || gs.phase !== 'playing' || gs.actionPhase !== 'postroll') return;

    const pid = gs.currentPlayerIndex;
    const player = gs.players[pid];
    const cost = getBuildCost('city', player.lord);

    if (!canAfford(player.resources, cost)) return;

    const buildingIdx = gs.buildings.findIndex(
      (b) => b.vertexId === vertexId && b.playerId === pid && b.type === 'village',
    );
    if (buildingIdx < 0) return;

    const newRes = deductCost(player.resources, cost);
    const newBuildings = gs.buildings.map((b, i) =>
      i === buildingIdx ? { ...b, type: 'city' as const } : b,
    );
    let newPlayers = gs.players.map((p, i) => (i === pid ? { ...p, resources: newRes } : p));
    newPlayers = updateSpecialAwards(newPlayers, newBuildings, gs.roads, gs.board);

    let s = log({ ...gs, players: newPlayers, buildings: newBuildings }, `🏰 ${player.name} köyü şehre yükseltti! (+1 ZP)`, 'build');

    const winner = checkWinner(s.players, s.buildings);
    if (winner !== null) s = { ...s, phase: 'ended', winner };

    set({ state: s });
    saveGame(s);
  },

  buildSoldier: () => {
    const gs = get().state;
    if (!gs || gs.phase !== 'playing' || gs.actionPhase !== 'postroll') return;

    const pid = gs.currentPlayerIndex;
    const player = gs.players[pid];
    const cost = getBuildCost('soldier', player.lord);

    if (!canAfford(player.resources, cost)) return;

    const newRes = deductCost(player.resources, cost);
    let newPlayers = gs.players.map((p, i) =>
      i === pid ? { ...p, resources: newRes, soldiers: p.soldiers + 1 } : p,
    );
    newPlayers = updateSpecialAwards(newPlayers, gs.buildings, gs.roads, gs.board);

    const s = log({ ...gs, players: newPlayers }, `⚔️ ${player.name} asker topladı! (Toplam: ${player.soldiers + 1})`, 'build');
    set({ state: s });
    saveGame(s);
  },

  bankTrade: (give: ResourceType, receive: ResourceType) => {
    const gs = get().state;
    if (!gs || gs.phase !== 'playing' || gs.actionPhase !== 'postroll') return;

    const pid = gs.currentPlayerIndex;
    const player = gs.players[pid];
    const rate = getTradeRate(give, gs.buildings, gs.board, pid, player.lord.type === 'merchant');

    if ((player.resources[give] ?? 0) < rate) return;

    const newRes = {
      ...player.resources,
      [give]: player.resources[give] - rate,
      [receive]: player.resources[receive] + 1,
    };

    const s = log(
      { ...gs, players: gs.players.map((p, i) => (i === pid ? { ...p, resources: newRes } : p)) },
      `🔄 ${player.name} takas yaptı: ${rate}x ${give} → 1x ${receive}`,
      'trade',
    );
    set({ state: s });
    saveGame(s);
  },

  offerTrade: (offer: TradeOffer) => {
    const gs = get().state;
    if (!gs || gs.phase !== 'playing' || gs.actionPhase !== 'postroll') return;

    const target = gs.players[offer.toPlayerId];

    if (target.isAI) {
      const accepted = aiEvalTradeOffer(offer, target, gs.buildings);
      if (accepted) {
        const newPlayers = doTrade(gs.players, offer);
        let s = log({ ...gs, players: newPlayers }, `🤝 ${target.name} teklifi kabul etti!`, 'trade');
        set({ state: s });
      } else {
        let s = log({ ...gs }, `❌ ${target.name} teklifi reddetti.`, 'trade');
        set({ state: s });
      }
    } else {
      // Human responds via modal
      set({ state: { ...gs, pendingTradeOffer: offer } });
    }
  },

  respondToTrade: (accept: boolean) => {
    const gs = get().state;
    if (!gs?.pendingTradeOffer) return;

    const offer = gs.pendingTradeOffer;
    if (accept) {
      const newPlayers = doTrade(gs.players, offer);
      let s = log({ ...gs, players: newPlayers, pendingTradeOffer: null }, `🤝 Ticaret tamamlandı!`, 'trade');
      set({ state: s });
    } else {
      let s = log({ ...gs, pendingTradeOffer: null }, `❌ Teklif reddedildi.`, 'trade');
      set({ state: s });
    }
    saveGame(get().state!);
  },

  attackBuilding: (targetVertexId: number) => {
    const gs = get().state;
    if (!gs || gs.phase !== 'playing' || gs.actionPhase !== 'postroll') return;
    if (gs.hasAttackedThisTurn) return;

    const pid = gs.currentPlayerIndex;
    const attacker = gs.players[pid];

    if (attacker.soldiers < 1) {
      let s = log(gs, `⚠️ Saldırı için en az 1 asker gerekli!`, 'combat');
      set({ state: s });
      return;
    }

    const targetBuilding = gs.buildings.find(
      (b) => b.vertexId === targetVertexId && b.playerId !== pid,
    );
    if (!targetBuilding) return;

    const { resolveCombat, pillageAmount } = require('../game/combat');
    const result = resolveCombat(attacker, gs.players[targetBuilding.playerId], targetBuilding, gs.roads, gs.board);

    let newBuildings = [...gs.buildings];
    let newPlayers = gs.players.map((p, i) => (i === pid ? { ...p, soldiers: p.soldiers - 1 } : p));

    if (result.attackerWins) {
      const idx = newBuildings.findIndex((b) => b.vertexId === targetVertexId && b.playerId !== pid);
      if (idx >= 0) {
        if (newBuildings[idx].type === 'city') {
          newBuildings[idx] = { ...newBuildings[idx], type: 'village' };
        } else {
          newBuildings.splice(idx, 1);
        }
      }

      // Pillage
      const pillage = pillageAmount(attacker);
      const defender = gs.players[targetBuilding.playerId];
      const defRes = Object.entries(defender.resources)
        .filter(([, v]) => v > 0)
        .map(([k]) => k as ResourceType);

      for (let i = 0; i < pillage && defRes.length > 0; i++) {
        const stolen = defRes[Math.floor(Math.random() * defRes.length)];
        newPlayers = newPlayers.map((p, idx2) => {
          if (idx2 === targetBuilding.playerId && p.resources[stolen] > 0) {
            return { ...p, resources: { ...p.resources, [stolen]: p.resources[stolen] - 1 } };
          }
          if (idx2 === pid) {
            return { ...p, resources: { ...p.resources, [stolen]: p.resources[stolen] + 1 } };
          }
          return p;
        });
      }
    }

    newPlayers = updateSpecialAwards(newPlayers, newBuildings, gs.roads, gs.board);

    let s = log(
      { ...gs, players: newPlayers, buildings: newBuildings, hasAttackedThisTurn: true },
      result.log,
      'combat',
    );

    const winner = checkWinner(s.players, s.buildings);
    if (winner !== null) s = { ...s, phase: 'ended', winner };

    set({ state: s });
    saveGame(s);
  },

  endTurn: () => {
    const gs = get().state;
    if (!gs || gs.phase !== 'playing') return;

    const nextIdx = (gs.currentPlayerIndex + 1) % gs.players.length;
    const nextPlayer = gs.players[nextIdx];
    const newTurn = nextIdx === 0 ? gs.turnNumber + 1 : gs.turnNumber;

    let s: GameState = {
      ...gs,
      currentPlayerIndex: nextIdx,
      actionPhase: 'preroll',
      diceValues: null,
      lastEvent: null,
      hasAttackedThisTurn: false,
      pendingRobberSteal: null,
      turnNumber: newTurn,
    };

    s = log(s, `🔄 ${nextPlayer.name}'nın turu.`, 'system');
    set({ state: s });
    saveGame(s);

    if (nextPlayer.isAI) {
      runAITurn(get, set);
    }
  },
}));

// ─── Helpers ──────────────────────────────────────────────────────────────────

function applyRobberMove(gs: GameState, hexId: number, stealFrom: number | null): GameState {
  const newHexes = gs.board.hexes.map((h) => ({ ...h, hasRobber: h.id === hexId }));
  let s: GameState = { ...gs, board: { ...gs.board, hexes: newHexes }, actionPhase: 'postroll' };

  if (stealFrom !== null && stealFrom >= 0) {
    const target = s.players[stealFrom];
    const defRes = Object.entries(target.resources)
      .filter(([, v]) => v > 0)
      .map(([k]) => k as ResourceType);

    if (defRes.length > 0) {
      const stolen = defRes[Math.floor(Math.random() * defRes.length)];
      const pid = gs.currentPlayerIndex;
      s = {
        ...s,
        players: s.players.map((p, i) => {
          if (i === stealFrom) return { ...p, resources: { ...p.resources, [stolen]: p.resources[stolen] - 1 } };
          if (i === pid) return { ...p, resources: { ...p.resources, [stolen]: p.resources[stolen] + 1 } };
          return p;
        }),
      };
      s = log(s, `🤜 ${gs.players[pid].name} haydutla ${s.players[stealFrom].name}'dan 1 kaynak çaldı!`, 'combat');
    }
  }

  s = log(s, `🦹 Haydut yeni konumuna taşındı.`, 'event');
  return s;
}

function doTrade(players: Player[], offer: TradeOffer): Player[] {
  return players.map((p) => {
    if (p.id === offer.fromPlayerId) {
      const r = { ...p.resources };
      for (const [k, v] of Object.entries(offer.give) as [ResourceType, number][]) r[k] = Math.max(0, r[k] - v);
      for (const [k, v] of Object.entries(offer.receive) as [ResourceType, number][]) r[k] = r[k] + v;
      return { ...p, resources: r };
    }
    if (p.id === offer.toPlayerId) {
      const r = { ...p.resources };
      for (const [k, v] of Object.entries(offer.receive) as [ResourceType, number][]) r[k] = Math.max(0, r[k] - v);
      for (const [k, v] of Object.entries(offer.give) as [ResourceType, number][]) r[k] = r[k] + v;
      return { ...p, resources: r };
    }
    return p;
  });
}

// ─── AI Turn ─────────────────────────────────────────────────────────────────

function runAITurn(
  get: () => GameStore,
  set: (partial: Partial<GameStore>) => void,
) {
  const store = get();

  // Roll dice
  setTimeout(() => {
    store.rollDice();

    setTimeout(() => {
      const gs2 = get().state;
      if (!gs2) return;

      // If robber phase, handled in rollDice for AI
      // Now do builds (try up to 3 times)
      let attempts = 0;
      const tryBuild = () => {
        const gs = get().state;
        if (!gs || gs.phase !== 'playing' || gs.actionPhase !== 'postroll') return;

        const pid = gs.currentPlayerIndex;
        const ai = gs.players[pid];
        if (!ai.isAI) return;

        if (attempts++ >= 3) {
          // Maybe offer trade
          const offer = aiGenerateOffer(ai, 0, gs.buildings);
          if (offer) {
            get().offerTrade(offer);
          }

          // Try attack
          const targets = validAttackTargets(gs.buildings, gs.board, pid);
          if (!gs.hasAttackedThisTurn && ai.soldiers >= 2 && targets.length > 0 && Math.random() < 0.4) {
            const target = targets.reduce((best, t) => {
              const tvp = totalVPs(gs.buildings, gs.players[t.playerId]);
              const bvp = totalVPs(gs.buildings, gs.players[best.playerId]);
              return tvp > bvp ? t : best;
            });
            get().attackBuilding(target.vertexId);
          }

          setTimeout(() => get().endTurn(), 800);
          return;
        }

        const action = aiDecideBuild(ai, gs.board, gs.buildings, gs.roads, gs.players);

        if (action.type === null) {
          attempts = 3; // Skip to attack/end
          tryBuild();
          return;
        }

        switch (action.type) {
          case 'city':
            if (action.vertexId !== undefined) get().buildCity(action.vertexId);
            break;
          case 'village':
            if (action.vertexId !== undefined) get().buildVillage(action.vertexId);
            break;
          case 'road':
            if (action.edgeId !== undefined) get().buildRoad(action.edgeId);
            break;
          case 'soldier':
            get().buildSoldier();
            break;
          case 'trade':
            if (action.tradeResource && action.tradeFor) {
              get().bankTrade(action.tradeResource, action.tradeFor);
            }
            break;
        }

        setTimeout(tryBuild, 600);
      };

      setTimeout(tryBuild, 500);
    }, 800);
  }, 500);
}
