import React from 'react';
import { Modal, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { GameState, ResourceType, TradeOffer } from '../game/types';

const RESOURCE_ICON: Record<ResourceType, string> = {
  wood: '🌲', stone: '⛰️', grain: '🌾', sheep: '🐑', iron: '⚒️',
};

interface OfferModalProps {
  offer: TradeOffer | null;
  gs: GameState;
  onAccept: () => void;
  onReject: () => void;
}

export function OfferModal({ offer, gs, onAccept, onReject }: OfferModalProps) {
  if (!offer) return null;

  const fromPlayer = gs.players[offer.fromPlayerId];
  const toPlayer = gs.players[offer.toPlayerId];

  const giveEntries = Object.entries(offer.give).filter(([, v]) => (v ?? 0) > 0) as [ResourceType, number][];
  const receiveEntries = Object.entries(offer.receive).filter(([, v]) => (v ?? 0) > 0) as [ResourceType, number][];

  return (
    <Modal visible={!!offer} transparent animationType="fade" onRequestClose={onReject}>
      <View style={styles.overlay}>
        <View style={styles.modal}>
          <Text style={styles.title}>🤝 Ticaret Teklifi!</Text>
          <Text style={styles.from}>
            {fromPlayer?.lord.emoji} <Text style={{ color: fromPlayer?.color }}>{fromPlayer?.name}</Text> sana teklif sunuyor:
          </Text>

          <View style={styles.tradeRow}>
            <View style={styles.side}>
              <Text style={styles.sideLabel}>Onlar veriyor:</Text>
              {giveEntries.map(([r, v]) => (
                <Text key={r} style={styles.resource}>
                  {RESOURCE_ICON[r]} {v}x {r}
                </Text>
              ))}
            </View>

            <Text style={styles.arrow}>⇄</Text>

            <View style={styles.side}>
              <Text style={styles.sideLabel}>Sen veriyorsun:</Text>
              {receiveEntries.map(([r, v]) => (
                <Text key={r} style={styles.resource}>
                  {RESOURCE_ICON[r]} {v}x {r}
                </Text>
              ))}
            </View>
          </View>

          <View style={styles.buttons}>
            <TouchableOpacity style={styles.rejectBtn} onPress={onReject}>
              <Text style={styles.rejectText}>❌ Reddet</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.acceptBtn} onPress={onAccept}>
              <Text style={styles.acceptText}>✅ Kabul Et</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.75)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modal: {
    backgroundColor: '#1a0f0a',
    borderRadius: 16,
    borderWidth: 2,
    borderColor: '#d9b061',
    padding: 20,
    width: '100%',
    maxWidth: 340,
  },
  title: {
    color: '#d9b061',
    fontSize: 20,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 10,
  },
  from: {
    color: '#f5e6c8',
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 16,
  },
  tradeRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    alignItems: 'center',
    marginBottom: 20,
    gap: 8,
  },
  side: {
    flex: 1,
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: 8,
    padding: 10,
  },
  sideLabel: {
    color: '#d9b061',
    fontSize: 11,
    fontWeight: '600',
    marginBottom: 6,
  },
  resource: {
    color: '#f5e6c8',
    fontSize: 13,
    marginBottom: 2,
  },
  arrow: {
    color: '#d9b061',
    fontSize: 24,
  },
  buttons: {
    flexDirection: 'row',
    gap: 12,
  },
  rejectBtn: {
    flex: 1,
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#e74c3c',
    alignItems: 'center',
  },
  acceptBtn: {
    flex: 1,
    padding: 12,
    borderRadius: 10,
    backgroundColor: '#27ae60',
    alignItems: 'center',
  },
  rejectText: {
    color: '#e74c3c',
    fontSize: 15,
    fontWeight: 'bold',
  },
  acceptText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: 'bold',
  },
});
