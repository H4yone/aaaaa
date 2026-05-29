import React, { useState } from 'react';
import { Modal, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { GameState, Player, ResourceCounts, ResourceType } from '../game/types';
import { canAfford, getTradeRate } from '../game/rules';
import { totalResources } from '../game/resources';

const RESOURCE_ICON: Record<ResourceType, string> = {
  wood: '🌲', stone: '⛰️', grain: '🌾', sheep: '🐑', iron: '⚒️',
};

const ALL_RES: ResourceType[] = ['wood', 'stone', 'grain', 'sheep', 'iron'];

interface TradeModalProps {
  visible: boolean;
  gs: GameState;
  onClose: () => void;
  onBankTrade: (give: ResourceType, receive: ResourceType) => void;
  onPlayerOffer: (give: Partial<ResourceCounts>, receive: Partial<ResourceCounts>, toPlayerId: number) => void;
}

export function TradeModal({ visible, gs, onClose, onBankTrade, onPlayerOffer }: TradeModalProps) {
  const [tab, setTab] = useState<'bank' | 'player'>('bank');
  const [selectedGive, setSelectedGive] = useState<ResourceType | null>(null);
  const [selectedReceive, setSelectedReceive] = useState<ResourceType | null>(null);
  const [giveAmounts, setGiveAmounts] = useState<Partial<ResourceCounts>>({});
  const [receiveAmounts, setReceiveAmounts] = useState<Partial<ResourceCounts>>({});
  const [targetPlayer, setTargetPlayer] = useState<number>(1);

  const player = gs.players[gs.currentPlayerIndex];
  const isMerchant = player.lord.type === 'merchant';

  const handleBankTrade = () => {
    if (!selectedGive || !selectedReceive || selectedGive === selectedReceive) return;
    onBankTrade(selectedGive, selectedReceive);
    setSelectedGive(null);
    setSelectedReceive(null);
  };

  const handlePlayerOffer = () => {
    const target = gs.players[targetPlayer];
    if (!target || !target.isAI) return;
    const hasGive = Object.values(giveAmounts).some((v) => (v ?? 0) > 0);
    const hasReceive = Object.values(receiveAmounts).some((v) => (v ?? 0) > 0);
    if (!hasGive || !hasReceive) return;

    // Check affordability
    if (!canAfford(player.resources, giveAmounts)) return;

    onPlayerOffer(giveAmounts, receiveAmounts, targetPlayer);
    setGiveAmounts({});
    setReceiveAmounts({});
    onClose();
  };

  const aiPlayers = gs.players.filter((p) => p.isAI);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <View style={styles.modal}>
          <View style={styles.header}>
            <Text style={styles.title}>🔄 Ticaret</Text>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
              <Text style={styles.closeText}>✕</Text>
            </TouchableOpacity>
          </View>

          {/* Tabs */}
          <View style={styles.tabs}>
            <TouchableOpacity
              style={[styles.tab, tab === 'bank' && styles.activeTab]}
              onPress={() => setTab('bank')}
            >
              <Text style={[styles.tabText, tab === 'bank' && styles.activeTabText]}>🏦 Banka</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tab, tab === 'player' && styles.activeTab]}
              onPress={() => setTab('player')}
            >
              <Text style={[styles.tabText, tab === 'player' && styles.activeTabText]}>🤝 Oyuncu</Text>
            </TouchableOpacity>
          </View>

          {tab === 'bank' ? (
            <ScrollView>
              <Text style={styles.section}>Vermek istediğin kaynak:</Text>
              <View style={styles.resourceRow}>
                {ALL_RES.map((r) => {
                  const rate = getTradeRate(r, gs.buildings, gs.board, player.id, isMerchant);
                  const canTrade = player.resources[r] >= rate;
                  return (
                    <TouchableOpacity
                      key={r}
                      style={[
                        styles.resBtn,
                        selectedGive === r && styles.resBtnSelected,
                        !canTrade && styles.resBtnDisabled,
                      ]}
                      onPress={() => canTrade && setSelectedGive(r)}
                      disabled={!canTrade}
                    >
                      <Text style={styles.resIcon}>{RESOURCE_ICON[r]}</Text>
                      <Text style={styles.resCount}>{player.resources[r]}</Text>
                      <Text style={styles.rate}>{rate}:1</Text>
                    </TouchableOpacity>
                  );
                })}
              </View>

              <Text style={styles.section}>Almak istediğin kaynak:</Text>
              <View style={styles.resourceRow}>
                {ALL_RES.map((r) => (
                  <TouchableOpacity
                    key={r}
                    style={[
                      styles.resBtn,
                      selectedReceive === r && styles.resBtnSelected,
                      selectedGive === r && styles.resBtnDisabled,
                    ]}
                    onPress={() => r !== selectedGive && setSelectedReceive(r)}
                    disabled={r === selectedGive}
                  >
                    <Text style={styles.resIcon}>{RESOURCE_ICON[r]}</Text>
                    <Text style={styles.resCount}>{player.resources[r]}</Text>
                  </TouchableOpacity>
                ))}
              </View>

              <TouchableOpacity
                style={[
                  styles.actionBtn,
                  (!selectedGive || !selectedReceive) && styles.actionBtnDisabled,
                ]}
                onPress={handleBankTrade}
                disabled={!selectedGive || !selectedReceive}
              >
                <Text style={styles.actionText}>Takas Yap ✓</Text>
              </TouchableOpacity>
            </ScrollView>
          ) : (
            <ScrollView>
              {aiPlayers.length === 0 ? (
                <Text style={styles.noAI}>Ticaret yapılacak rakip yok.</Text>
              ) : (
                <>
                  <Text style={styles.section}>Rakip Seç:</Text>
                  <View style={styles.playerRow}>
                    {aiPlayers.map((p) => (
                      <TouchableOpacity
                        key={p.id}
                        style={[styles.playerBtn, targetPlayer === p.id && styles.playerBtnSelected, { borderColor: p.color }]}
                        onPress={() => setTargetPlayer(p.id)}
                      >
                        <Text style={styles.playerBtnText}>{p.lord.emoji} {p.name}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>

                  <Text style={styles.section}>Sen Veriyorsun:</Text>
                  <View style={styles.resourceRow}>
                    {ALL_RES.map((r) => (
                      <ResourceStepper
                        key={r}
                        resource={r}
                        max={player.resources[r]}
                        value={giveAmounts[r] ?? 0}
                        onChange={(v) => setGiveAmounts((prev) => ({ ...prev, [r]: v }))}
                      />
                    ))}
                  </View>

                  <Text style={styles.section}>Sen Alıyorsun:</Text>
                  <View style={styles.resourceRow}>
                    {ALL_RES.map((r) => (
                      <ResourceStepper
                        key={r}
                        resource={r}
                        max={99}
                        value={receiveAmounts[r] ?? 0}
                        onChange={(v) => setReceiveAmounts((prev) => ({ ...prev, [r]: v }))}
                      />
                    ))}
                  </View>

                  <TouchableOpacity
                    style={[styles.actionBtn, styles.offerBtn]}
                    onPress={handlePlayerOffer}
                  >
                    <Text style={styles.actionText}>Teklif Gönder ✉️</Text>
                  </TouchableOpacity>
                </>
              )}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

function ResourceStepper({
  resource,
  max,
  value,
  onChange,
}: {
  resource: ResourceType;
  max: number;
  value: number;
  onChange: (v: number) => void;
}) {
  const ICONS: Record<ResourceType, string> = {
    wood: '🌲', stone: '⛰️', grain: '🌾', sheep: '🐑', iron: '⚒️',
  };

  return (
    <View style={styles.stepper}>
      <Text style={styles.stepperIcon}>{ICONS[resource]}</Text>
      <TouchableOpacity
        style={styles.stepBtn}
        onPress={() => onChange(Math.max(0, value - 1))}
        disabled={value <= 0}
      >
        <Text style={[styles.stepBtnText, value <= 0 && styles.disabled]}>−</Text>
      </TouchableOpacity>
      <Text style={styles.stepValue}>{value}</Text>
      <TouchableOpacity
        style={styles.stepBtn}
        onPress={() => onChange(Math.min(max, value + 1))}
        disabled={value >= max}
      >
        <Text style={[styles.stepBtnText, value >= max && styles.disabled]}>+</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  modal: {
    backgroundColor: '#1a0f0a',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    borderTopWidth: 2,
    borderColor: '#d9b061',
    maxHeight: '80%',
    padding: 16,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  title: {
    color: '#d9b061',
    fontSize: 18,
    fontWeight: 'bold',
  },
  closeBtn: {
    padding: 8,
  },
  closeText: {
    color: '#d9b061',
    fontSize: 18,
  },
  tabs: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
  },
  tab: {
    flex: 1,
    padding: 10,
    backgroundColor: 'rgba(217,176,97,0.1)',
    borderRadius: 8,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(217,176,97,0.3)',
  },
  activeTab: {
    backgroundColor: 'rgba(217,176,97,0.25)',
    borderColor: '#d9b061',
  },
  tabText: {
    color: '#aaa',
    fontSize: 14,
  },
  activeTabText: {
    color: '#d9b061',
    fontWeight: 'bold',
  },
  section: {
    color: '#d9b061',
    fontSize: 13,
    fontWeight: '600',
    marginBottom: 8,
    marginTop: 4,
  },
  resourceRow: {
    flexDirection: 'row',
    gap: 8,
    flexWrap: 'wrap',
    marginBottom: 12,
  },
  resBtn: {
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: 8,
    borderWidth: 2,
    borderColor: 'rgba(255,255,255,0.15)',
    paddingHorizontal: 10,
    paddingVertical: 8,
    minWidth: 56,
  },
  resBtnSelected: {
    borderColor: '#d9b061',
    backgroundColor: 'rgba(217,176,97,0.15)',
  },
  resBtnDisabled: {
    opacity: 0.35,
  },
  resIcon: {
    fontSize: 20,
  },
  resCount: {
    color: '#f5e6c8',
    fontSize: 14,
    fontWeight: 'bold',
  },
  rate: {
    color: '#d9b061',
    fontSize: 10,
  },
  actionBtn: {
    backgroundColor: '#d9b061',
    borderRadius: 10,
    padding: 14,
    alignItems: 'center',
    marginTop: 8,
  },
  offerBtn: {
    backgroundColor: '#8e44ad',
  },
  actionBtnDisabled: {
    opacity: 0.4,
  },
  actionText: {
    color: '#2c1810',
    fontSize: 15,
    fontWeight: 'bold',
  },
  playerRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
    flexWrap: 'wrap',
  },
  playerBtn: {
    borderWidth: 2,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: 'rgba(255,255,255,0.06)',
  },
  playerBtnSelected: {
    backgroundColor: 'rgba(255,255,255,0.15)',
  },
  playerBtnText: {
    color: '#f5e6c8',
    fontSize: 13,
  },
  stepper: {
    alignItems: 'center',
    gap: 2,
  },
  stepperIcon: {
    fontSize: 18,
  },
  stepBtn: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: 'rgba(217,176,97,0.2)',
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#d9b061',
  },
  stepBtnText: {
    color: '#d9b061',
    fontSize: 16,
    fontWeight: 'bold',
  },
  stepValue: {
    color: '#f5e6c8',
    fontSize: 14,
    fontWeight: 'bold',
    minWidth: 20,
    textAlign: 'center',
  },
  disabled: {
    opacity: 0.3,
  },
  noAI: {
    color: '#aaa',
    textAlign: 'center',
    marginVertical: 20,
  },
});
