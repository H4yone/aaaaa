import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Player, ResourceCounts, ResourceType } from '../game/types';

const RESOURCE_ICON: Record<ResourceType, string> = {
  wood: '🌲',
  stone: '⛰️',
  grain: '🌾',
  sheep: '🐑',
  iron: '⚒️',
};

const RESOURCE_LABEL: Record<ResourceType, string> = {
  wood: 'Kereste',
  stone: 'Taş',
  grain: 'Tahıl',
  sheep: 'Koyun',
  iron: 'Demir',
};

const RESOURCE_COLOR: Record<ResourceType, string> = {
  wood: '#2d6a1f',
  stone: '#6b6b6b',
  grain: '#b8860b',
  sheep: '#4a8c28',
  iron: '#7a4a2a',
};

interface ResourcePanelProps {
  player: Player;
  compact?: boolean;
}

export function ResourcePanel({ player, compact = false }: ResourcePanelProps) {
  const resources: ResourceType[] = ['wood', 'stone', 'grain', 'sheep', 'iron'];

  if (compact) {
    return (
      <View style={styles.compact}>
        {resources.map((r) => (
          <View key={r} style={styles.compactItem}>
            <Text style={styles.compactIcon}>{RESOURCE_ICON[r]}</Text>
            <Text style={[styles.compactCount, { color: RESOURCE_COLOR[r] }]}>
              {player.resources[r]}
            </Text>
          </View>
        ))}
        <View style={styles.compactItem}>
          <Text style={styles.compactIcon}>⚔️</Text>
          <Text style={[styles.compactCount, { color: '#c0392b' }]}>{player.soldiers}</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.panel}>
      <Text style={styles.title}>{player.lord.emoji} {player.name}</Text>
      <View style={styles.row}>
        {resources.map((r) => (
          <View key={r} style={[styles.resource, { borderColor: RESOURCE_COLOR[r] }]}>
            <Text style={styles.icon}>{RESOURCE_ICON[r]}</Text>
            <Text style={[styles.count, { color: RESOURCE_COLOR[r] }]}>
              {player.resources[r]}
            </Text>
            {!compact && (
              <Text style={styles.label}>{RESOURCE_LABEL[r]}</Text>
            )}
          </View>
        ))}
        <View style={[styles.resource, { borderColor: '#c0392b' }]}>
          <Text style={styles.icon}>⚔️</Text>
          <Text style={[styles.count, { color: '#c0392b' }]}>{player.soldiers}</Text>
          {!compact && <Text style={styles.label}>Asker</Text>}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: 'rgba(44, 24, 16, 0.92)',
    borderRadius: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: '#d9b061',
  },
  title: {
    color: '#d9b061',
    fontSize: 14,
    fontWeight: 'bold',
    marginBottom: 8,
    textAlign: 'center',
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    flexWrap: 'wrap',
    gap: 4,
  },
  resource: {
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: 8,
    borderWidth: 1,
    paddingHorizontal: 6,
    paddingVertical: 4,
    minWidth: 44,
  },
  icon: {
    fontSize: 18,
  },
  count: {
    fontSize: 18,
    fontWeight: 'bold',
  },
  label: {
    fontSize: 9,
    color: '#ccc',
    marginTop: 1,
  },
  // Compact styles
  compact: {
    flexDirection: 'row',
    gap: 6,
    alignItems: 'center',
  },
  compactItem: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 2,
  },
  compactIcon: {
    fontSize: 12,
  },
  compactCount: {
    fontSize: 12,
    fontWeight: 'bold',
  },
});
