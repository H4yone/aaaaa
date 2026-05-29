import React from 'react';
import { Animated, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { GameState } from '../game/types';
import { totalVPs } from '../game/scoring';

interface Props {
  gs: GameState;
  onReplay: () => void;
  onMenu: () => void;
}

export function GameEndScreen({ gs, onReplay, onMenu }: Props) {
  const winner = gs.winner !== null ? gs.players[gs.winner] : null;

  const sorted = [...gs.players].sort((a, b) => {
    return totalVPs(gs.buildings, b) - totalVPs(gs.buildings, a);
  });

  const fadeAnim = React.useRef(new Animated.Value(0)).current;
  React.useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 800, useNativeDriver: true }).start();
  }, []);

  return (
    <Animated.View style={[styles.container, { opacity: fadeAnim }]}>
      <View style={styles.content}>
        {/* Winner announcement */}
        <View style={styles.winnerBlock}>
          <Text style={styles.crown}>👑</Text>
          <Text style={styles.winnerText}>{winner?.name}</Text>
          <Text style={styles.winnerSub}>Kazanan!</Text>
          {winner && (
            <Text style={styles.winnerLord}>
              {winner.lord.emoji} {winner.lord.name}
            </Text>
          )}
        </View>

        {/* Final scores */}
        <View style={styles.scoresBlock}>
          <Text style={styles.scoresTitle}>🏆 Final Skorları</Text>
          {sorted.map((p, i) => {
            const vp = totalVPs(gs.buildings, p);
            return (
              <View key={p.id} style={[styles.scoreRow, { borderLeftColor: p.color }]}>
                <Text style={styles.rank}>{i + 1}.</Text>
                <Text style={styles.scoreName}>
                  {p.lord.emoji} {p.name}
                </Text>
                <View style={styles.scoreDetails}>
                  <Text style={[styles.scoreVP, { color: p.color }]}>{vp} ZP</Text>
                  {p.hasLargestArmy && <Text style={styles.badge}>🗡️</Text>}
                  {p.hasLongestRoad && <Text style={styles.badge}>🛤️</Text>}
                </View>
              </View>
            );
          })}
        </View>

        {/* Stats */}
        <View style={styles.statsRow}>
          <Text style={styles.stat}>⏱️ {gs.turnNumber} Tur</Text>
          <Text style={styles.stat}>🏘️ {gs.buildings.filter((b) => b.type === 'village').length} Köy</Text>
          <Text style={styles.stat}>🏰 {gs.buildings.filter((b) => b.type === 'city').length} Şehir</Text>
        </View>

        {/* Buttons */}
        <View style={styles.buttons}>
          <TouchableOpacity style={styles.replayBtn} onPress={onReplay}>
            <Text style={styles.replayText}>⚔️ Yeniden Oyna</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.menuBtn} onPress={onMenu}>
            <Text style={styles.menuText}>🏠 Ana Menü</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0905',
    justifyContent: 'center',
    padding: 20,
  },
  content: {
    gap: 20,
  },
  winnerBlock: {
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(217,176,97,0.1)',
    borderRadius: 16,
    padding: 24,
    borderWidth: 2,
    borderColor: '#d9b061',
  },
  crown: {
    fontSize: 48,
  },
  winnerText: {
    color: '#d9b061',
    fontSize: 28,
    fontWeight: 'bold',
  },
  winnerSub: {
    color: '#b08040',
    fontSize: 16,
    fontStyle: 'italic',
  },
  winnerLord: {
    color: '#f5e6c8',
    fontSize: 14,
    marginTop: 4,
  },
  scoresBlock: {
    backgroundColor: 'rgba(44, 24, 16, 0.85)',
    borderRadius: 12,
    padding: 14,
    borderWidth: 1,
    borderColor: 'rgba(217,176,97,0.3)',
    gap: 8,
  },
  scoresTitle: {
    color: '#d9b061',
    fontSize: 15,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  scoreRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderLeftWidth: 3,
    paddingLeft: 8,
    gap: 8,
  },
  rank: {
    color: '#888',
    fontSize: 14,
    width: 20,
  },
  scoreName: {
    color: '#f5e6c8',
    fontSize: 14,
    flex: 1,
  },
  scoreDetails: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  scoreVP: {
    fontSize: 14,
    fontWeight: 'bold',
  },
  badge: {
    fontSize: 14,
  },
  statsRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 16,
  },
  stat: {
    color: '#888',
    fontSize: 12,
  },
  buttons: {
    gap: 12,
  },
  replayBtn: {
    backgroundColor: '#d9b061',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
  },
  replayText: {
    color: '#2c1810',
    fontSize: 16,
    fontWeight: 'bold',
  },
  menuBtn: {
    borderWidth: 1.5,
    borderColor: '#d9b061',
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
  },
  menuText: {
    color: '#d9b061',
    fontSize: 16,
  },
});
