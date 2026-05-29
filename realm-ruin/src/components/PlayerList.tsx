import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Building, Player } from '../game/types';
import { totalVPs } from '../game/scoring';

interface PlayerListProps {
  players: Player[];
  currentIdx: number;
  buildings: Building[];
}

export function PlayerList({ players, currentIdx, buildings }: PlayerListProps) {
  return (
    <View style={styles.container}>
      {players.map((p, i) => {
        const vp = totalVPs(buildings, p);
        const isCurrent = i === currentIdx;
        return (
          <View
            key={p.id}
            style={[styles.row, isCurrent && styles.active, { borderLeftColor: p.color }]}
          >
            <Text style={styles.lord}>{p.lord.emoji}</Text>
            <View style={styles.info}>
              <Text style={[styles.name, isCurrent && styles.activeName]} numberOfLines={1}>
                {p.name}
              </Text>
              <View style={styles.badges}>
                {p.hasLargestArmy && <Text style={styles.badge}>🗡️ Büyük Ordu</Text>}
                {p.hasLongestRoad && <Text style={styles.badge}>🛤️ Uzun Yol</Text>}
              </View>
            </View>
            <View style={styles.stats}>
              <Text style={[styles.vp, { color: p.color }]}>{vp} ZP</Text>
              <Text style={styles.stat}>⚔️{p.soldiers}</Text>
            </View>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: 4,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(44, 24, 16, 0.85)',
    borderRadius: 8,
    padding: 8,
    borderLeftWidth: 4,
    gap: 8,
  },
  active: {
    backgroundColor: 'rgba(217, 176, 97, 0.15)',
    borderWidth: 1,
    borderColor: '#d9b061',
    borderLeftWidth: 4,
  },
  lord: {
    fontSize: 20,
  },
  info: {
    flex: 1,
  },
  name: {
    color: '#f5e6c8',
    fontSize: 13,
    fontWeight: '600',
  },
  activeName: {
    color: '#d9b061',
  },
  badges: {
    flexDirection: 'row',
    gap: 4,
    flexWrap: 'wrap',
  },
  badge: {
    fontSize: 9,
    color: '#d9b061',
    backgroundColor: 'rgba(217,176,97,0.15)',
    paddingHorizontal: 4,
    borderRadius: 4,
  },
  stats: {
    alignItems: 'flex-end',
    gap: 2,
  },
  vp: {
    fontSize: 14,
    fontWeight: 'bold',
  },
  stat: {
    fontSize: 11,
    color: '#ccc',
  },
});
