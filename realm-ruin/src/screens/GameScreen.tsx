import React, { useCallback, useState } from 'react';
import {
  Alert,
  Dimensions,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { HexBoard } from '../components/HexBoard';
import { ResourcePanel } from '../components/ResourcePanel';
import { DiceDisplay } from '../components/DiceDisplay';
import { EventLog } from '../components/EventLog';
import { PlayerList } from '../components/PlayerList';
import { TradeModal } from '../components/TradeModal';
import { OfferModal } from '../components/OfferModal';
import { useGameStore } from '../state/gameStore';
import { canAfford, getBuildCost, validAttackTargets } from '../game/rules';
import { ResourceCounts, ResourceType } from '../game/types';

type BuildMode = 'none' | 'village' | 'road' | 'city' | 'robber' | 'attack';

export function GameScreen() {
  const {
    state: gs,
    rollDice,
    moveRobber,
    stealResource,
    buildVillage,
    buildRoad,
    buildCity,
    buildSoldier,
    bankTrade,
    offerTrade,
    respondToTrade,
    attackBuilding,
    endTurn,
  } = useGameStore();

  const [buildMode, setBuildMode] = useState<BuildMode>('none');
  const [showTrade, setShowTrade] = useState(false);
  const [showLog, setShowLog] = useState(false);

  if (!gs) return null;

  const pid = gs.currentPlayerIndex;
  const player = gs.players[pid];
  const isHumanTurn = !player.isAI && gs.phase === 'playing';
  const isSetupTurn = gs.phase === 'setup' && !gs.setup.pendingRoad && !gs.players[gs.currentPlayerIndex].isAI;
  const isSetupRoad = gs.phase === 'setup' && gs.setup.pendingRoad && !gs.players[gs.currentPlayerIndex].isAI;

  // --- Board interaction mode ---
  const getBoardMode = () => {
    if (gs.phase === 'setup') {
      if (isSetupRoad) return 'setup_road';
      if (isSetupTurn) return 'setup_village';
      return 'view';
    }
    if (gs.actionPhase === 'robber') return 'robber';
    if (buildMode === 'village') return 'place_village';
    if (buildMode === 'road') return 'place_road';
    if (buildMode === 'city') return 'place_city';
    if (buildMode === 'attack') return 'attack';
    return 'view';
  };

  const handleVertexPress = useCallback(
    (vertexId: number) => {
      if (gs.phase === 'setup') {
        useGameStore.getState().placeSetupVillage(vertexId);
      } else if (buildMode === 'village') {
        buildVillage(vertexId);
        setBuildMode('none');
      } else if (buildMode === 'city') {
        buildCity(vertexId);
        setBuildMode('none');
      } else if (buildMode === 'attack') {
        attackBuilding(vertexId);
        setBuildMode('none');
      }
    },
    [gs.phase, buildMode, buildVillage, buildCity, attackBuilding],
  );

  const handleEdgePress = useCallback(
    (edgeId: number) => {
      if (gs.phase === 'setup') {
        useGameStore.getState().placeSetupRoad(edgeId);
      } else if (buildMode === 'road') {
        buildRoad(edgeId);
        setBuildMode('none');
      }
    },
    [gs.phase, buildMode, buildRoad],
  );

  const handleHexPress = useCallback(
    (hexId: number) => {
      if (gs.actionPhase === 'robber') {
        moveRobber(hexId);
      }
    },
    [gs.actionPhase, moveRobber],
  );

  const boardMode = getBoardMode();

  // --- Status text ---
  const getStatusText = () => {
    if (gs.phase === 'setup') {
      if (gs.players[gs.currentPlayerIndex].isAI) {
        return `⏳ ${gs.players[gs.currentPlayerIndex].name} yerleştiriyor...`;
      }
      if (isSetupRoad) return '🛤️ Köyün bitişiğine yol kur';
      if (isSetupTurn) return '🏘️ Köy kurmak için bir yere dokun';
      return '⏳ Sıra değişiyor...';
    }
    if (!isHumanTurn) return `⏳ ${player.name} oynuyor...`;
    if (gs.actionPhase === 'preroll') return '🎲 Zar atmak için butona bas!';
    if (gs.actionPhase === 'robber') return '🦹 Haydutları taşı! Bir bölgeye dokun.';
    if (gs.pendingRobberSteal !== null && gs.pendingRobberSteal >= 0) {
      return `🤜 ${gs.players[gs.pendingRobberSteal].name}'dan çal!`;
    }
    if (buildMode === 'village') return '🏘️ Köy kurmak için bir yere dokun';
    if (buildMode === 'road') return '🛤️ Yol kurmak için bir kenar seç';
    if (buildMode === 'city') return '🏰 Yükseltmek için köyüne dokun';
    if (buildMode === 'attack') return '⚔️ Saldırmak için bir yapıya dokun';
    return '🎮 Hamlenizi yapın';
  };

  // --- Costs for current player ---
  const villageCost = getBuildCost('village', player.lord);
  const roadCost = getBuildCost('road', player.lord);
  const cityCost = getBuildCost('city', player.lord);
  const soldierCost = getBuildCost('soldier', player.lord);

  const canBuildVillage = canAfford(player.resources, villageCost);
  const canBuildRoad = canAfford(player.resources, roadCost);
  const canBuildCity = canAfford(player.resources, cityCost);
  const canBuildSoldier = canAfford(player.resources, soldierCost);
  const canAttack = !gs.hasAttackedThisTurn &&
    player.soldiers >= 1 &&
    validAttackTargets(gs.buildings, gs.board, pid).length > 0;

  const postRoll = gs.actionPhase === 'postroll' && isHumanTurn;

  return (
    <SafeAreaView style={styles.safe}>
      {/* Header bar */}
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Text style={styles.turn}>Tur {gs.turnNumber}</Text>
          <Text style={[styles.currentPlayer, { color: player.color }]}>
            {player.lord.emoji} {player.name}
          </Text>
        </View>
        <DiceDisplay values={gs.diceValues} />
        <View style={styles.headerRight}>
          <Text style={styles.vpText}>🏆 10 ZP</Text>
          <TouchableOpacity style={styles.logBtn} onPress={() => setShowLog(!showLog)}>
            <Text style={styles.logBtnText}>📜</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Status text */}
      <View style={styles.statusBar}>
        <Text style={styles.statusText}>{getStatusText()}</Text>
      </View>

      {/* Board */}
      <View style={styles.boardArea}>
        <HexBoard
          gs={gs}
          mode={boardMode}
          onVertexPress={handleVertexPress}
          onEdgePress={handleEdgePress}
          onHexPress={handleHexPress}
        />
      </View>

      {/* Pending steal button */}
      {gs.pendingRobberSteal !== null && gs.pendingRobberSteal >= 0 && (
        <TouchableOpacity
          style={styles.stealBtn}
          onPress={() => stealResource(gs.pendingRobberSteal!)}
        >
          <Text style={styles.stealText}>
            🤜 {gs.players[gs.pendingRobberSteal].name}'dan Çal!
          </Text>
        </TouchableOpacity>
      )}

      {/* Resource panel */}
      <View style={styles.resourceArea}>
        <ResourcePanel player={player} />
      </View>

      {/* Event log overlay */}
      {showLog && (
        <View style={styles.logOverlay}>
          <EventLog log={gs.log} maxHeight={200} />
        </View>
      )}

      {/* Player list */}
      <View style={styles.playerListArea}>
        <PlayerList
          players={gs.players}
          currentIdx={gs.currentPlayerIndex}
          buildings={gs.buildings}
        />
      </View>

      {/* Action buttons */}
      <ScrollView horizontal style={styles.actionBar} contentContainerStyle={styles.actionBarContent}>
        {/* Roll dice */}
        {isHumanTurn && gs.actionPhase === 'preroll' && (
          <ActionBtn
            label="🎲 Zar At"
            onPress={rollDice}
            variant="primary"
          />
        )}

        {/* Build buttons */}
        {postRoll && (
          <>
            <ActionBtn
              label="🏘️ Köy"
              onPress={() => setBuildMode(buildMode === 'village' ? 'none' : 'village')}
              active={buildMode === 'village'}
              disabled={!canBuildVillage}
              hint="1🌲1⛰️1🌾1🐑"
            />
            <ActionBtn
              label="🏰 Şehir"
              onPress={() => setBuildMode(buildMode === 'city' ? 'none' : 'city')}
              active={buildMode === 'city'}
              disabled={!canBuildCity}
              hint="2🌾3⚒️"
            />
            <ActionBtn
              label="🛤️ Yol"
              onPress={() => setBuildMode(buildMode === 'road' ? 'none' : 'road')}
              active={buildMode === 'road'}
              disabled={!canBuildRoad}
              hint="1🌲1⛰️"
            />
            <ActionBtn
              label="⚔️ Asker"
              onPress={() => { buildSoldier(); setBuildMode('none'); }}
              disabled={!canBuildSoldier}
              hint="1🐑1🌾1⚒️"
            />
            <ActionBtn
              label="🔄 Ticaret"
              onPress={() => setShowTrade(true)}
              variant="secondary"
            />
            <ActionBtn
              label="🗡️ Saldır"
              onPress={() => setBuildMode(buildMode === 'attack' ? 'none' : 'attack')}
              active={buildMode === 'attack'}
              disabled={!canAttack}
              variant="danger"
            />
            <ActionBtn
              label="✓ Turu Bitir"
              onPress={() => { endTurn(); setBuildMode('none'); }}
              variant="primary"
            />
          </>
        )}

        {/* Robber mode: handled via board tap, just show cancel */}
        {isHumanTurn && gs.actionPhase === 'robber' && (
          <Text style={styles.robberHint}>
            🦹 Haydutları yerleştirmek için haritada bir bölgeye dokun
          </Text>
        )}
      </ScrollView>

      {/* Modals */}
      {showTrade && (
        <TradeModal
          visible={showTrade}
          gs={gs}
          onClose={() => setShowTrade(false)}
          onBankTrade={(give, receive) => {
            bankTrade(give, receive);
          }}
          onPlayerOffer={(give, receive, toPlayerId) => {
            offerTrade({
              fromPlayerId: gs.currentPlayerIndex,
              toPlayerId,
              give: give as ResourceCounts,
              receive: receive as ResourceCounts,
            });
          }}
        />
      )}

      <OfferModal
        offer={gs.pendingTradeOffer}
        gs={gs}
        onAccept={() => respondToTrade(true)}
        onReject={() => respondToTrade(false)}
      />
    </SafeAreaView>
  );
}

// ─── Action Button Component ──────────────────────────────────────────────────

interface ActionBtnProps {
  label: string;
  hint?: string;
  onPress: () => void;
  disabled?: boolean;
  active?: boolean;
  variant?: 'default' | 'primary' | 'secondary' | 'danger';
}

function ActionBtn({ label, hint, onPress, disabled, active, variant = 'default' }: ActionBtnProps) {
  const bgColor = active
    ? '#d9b061'
    : variant === 'primary'
    ? '#d9b061'
    : variant === 'secondary'
    ? '#8e44ad'
    : variant === 'danger'
    ? 'rgba(231,76,60,0.15)'
    : 'rgba(255,255,255,0.07)';

  const textColor = active || variant === 'primary' ? '#2c1810' : variant === 'danger' ? '#e74c3c' : '#f5e6c8';
  const borderColor = active
    ? '#d9b061'
    : variant === 'primary'
    ? '#d9b061'
    : variant === 'danger'
    ? '#e74c3c'
    : 'rgba(217,176,97,0.3)';

  return (
    <TouchableOpacity
      style={[
        styles.actionBtn,
        { backgroundColor: bgColor, borderColor },
        disabled && styles.actionBtnDisabled,
      ]}
      onPress={onPress}
      disabled={disabled}
    >
      <Text style={[styles.actionBtnText, { color: textColor }, disabled && styles.disabledText]}>
        {label}
      </Text>
      {hint && (
        <Text style={[styles.actionBtnHint, disabled && styles.disabledText]}>{hint}</Text>
      )}
    </TouchableOpacity>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#0f0905',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: '#1a0f0a',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(217,176,97,0.3)',
  },
  headerLeft: {
    gap: 2,
    minWidth: 90,
  },
  headerRight: {
    gap: 2,
    alignItems: 'flex-end',
    minWidth: 50,
  },
  turn: {
    color: '#888',
    fontSize: 11,
  },
  currentPlayer: {
    fontSize: 13,
    fontWeight: 'bold',
  },
  vpText: {
    color: '#d9b061',
    fontSize: 12,
    fontWeight: 'bold',
  },
  logBtn: {
    padding: 4,
  },
  logBtnText: {
    fontSize: 16,
  },
  statusBar: {
    backgroundColor: 'rgba(44,24,16,0.95)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(217,176,97,0.2)',
  },
  statusText: {
    color: '#f5e6c8',
    fontSize: 12,
    textAlign: 'center',
  },
  boardArea: {
    flex: 1,
  },
  resourceArea: {
    padding: 8,
  },
  logOverlay: {
    position: 'absolute',
    top: 80,
    right: 8,
    left: 8,
    zIndex: 10,
  },
  playerListArea: {
    paddingHorizontal: 8,
    paddingBottom: 4,
  },
  actionBar: {
    maxHeight: 80,
    backgroundColor: '#1a0f0a',
    borderTopWidth: 1,
    borderTopColor: 'rgba(217,176,97,0.3)',
  },
  actionBarContent: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 10,
    gap: 8,
  },
  actionBtn: {
    borderWidth: 1.5,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    alignItems: 'center',
    minWidth: 72,
  },
  actionBtnDisabled: {
    opacity: 0.35,
  },
  actionBtnText: {
    fontSize: 12,
    fontWeight: '600',
  },
  actionBtnHint: {
    fontSize: 9,
    color: '#aaa',
    marginTop: 2,
  },
  disabledText: {
    color: '#666',
  },
  stealBtn: {
    backgroundColor: '#c0392b',
    padding: 12,
    alignItems: 'center',
    borderRadius: 8,
    margin: 8,
  },
  stealText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 14,
  },
  robberHint: {
    color: '#e67e22',
    fontSize: 12,
    padding: 12,
    flex: 1,
  },
});
