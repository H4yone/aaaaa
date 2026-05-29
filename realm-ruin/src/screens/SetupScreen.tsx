import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { LORD_LIST } from '../game/lords';
import { Lord, LordType } from '../game/types';

interface Props {
  onStart: (playerCount: number, lordChoices: number[]) => void;
  onBack: () => void;
}

export function SetupScreen({ onStart, onBack }: Props) {
  const [playerCount, setPlayerCount] = useState(3);
  const [lordChoices, setLordChoices] = useState<number[]>([0, 1, 2, 3]);

  const handleStart = () => {
    onStart(playerCount, lordChoices.slice(0, playerCount));
  };

  const playerNames = ['Sen', 'Lord Aldric', 'Lady Mira', 'Baron Vex'];

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={onBack} style={styles.backBtn}>
          <Text style={styles.backText}>← Geri</Text>
        </TouchableOpacity>
        <Text style={styles.title}>⚔️ Yeni Oyun</Text>
        <View style={{ width: 60 }} />
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        {/* Player count */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Oyuncu Sayısı</Text>
          <View style={styles.countRow}>
            {[2, 3, 4].map((n) => (
              <TouchableOpacity
                key={n}
                style={[styles.countBtn, playerCount === n && styles.countBtnSelected]}
                onPress={() => setPlayerCount(n)}
              >
                <Text style={[styles.countText, playerCount === n && styles.countTextSelected]}>
                  {n}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          <Text style={styles.hint}>1 İnsan + {playerCount - 1} Yapay Zeka</Text>
        </View>

        {/* Lord selection */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Lord Seçimi</Text>

          {Array.from({ length: playerCount }, (_, i) => (
            <View key={i} style={styles.playerSection}>
              <Text style={[styles.playerName, i === 0 ? styles.humanName : styles.aiName]}>
                {i === 0 ? '👤' : '🤖'} {playerNames[i]}
              </Text>

              {i === 0 ? (
                // Human chooses their lord
                <View style={styles.lordsGrid}>
                  {LORD_LIST.map((lord, idx) => {
                    const selected = lordChoices[0] === idx;
                    return (
                      <TouchableOpacity
                        key={lord.type}
                        style={[styles.lordCard, selected && styles.lordCardSelected]}
                        onPress={() => {
                          const next = [...lordChoices];
                          next[0] = idx;
                          setLordChoices(next);
                        }}
                      >
                        <Text style={styles.lordEmoji}>{lord.emoji}</Text>
                        <Text style={[styles.lordName, selected && styles.lordNameSelected]}>
                          {lord.name}
                        </Text>
                        <Text style={styles.lordDesc}>{lord.description}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              ) : (
                <View style={styles.aiLord}>
                  <Text style={styles.aiLordIcon}>{LORD_LIST[lordChoices[i] ?? i]?.emoji ?? '🎲'}</Text>
                  <Text style={styles.aiLordText}>
                    Rastgele — {LORD_LIST[i % LORD_LIST.length].name}
                  </Text>
                </View>
              )}
            </View>
          ))}
        </View>

        <TouchableOpacity style={styles.startBtn} onPress={handleStart}>
          <Text style={styles.startText}>⚔️ Oyunu Başlat!</Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0905',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    paddingTop: 50,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(217,176,97,0.3)',
  },
  backBtn: {
    padding: 8,
  },
  backText: {
    color: '#d9b061',
    fontSize: 15,
  },
  title: {
    color: '#d9b061',
    fontSize: 18,
    fontWeight: 'bold',
  },
  content: {
    padding: 16,
    gap: 20,
    paddingBottom: 40,
  },
  section: {
    gap: 12,
  },
  sectionTitle: {
    color: '#d9b061',
    fontSize: 16,
    fontWeight: 'bold',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(217,176,97,0.3)',
    paddingBottom: 6,
  },
  countRow: {
    flexDirection: 'row',
    gap: 12,
  },
  countBtn: {
    width: 60,
    height: 60,
    borderRadius: 30,
    borderWidth: 2,
    borderColor: '#d9b061',
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(217,176,97,0.08)',
  },
  countBtnSelected: {
    backgroundColor: '#d9b061',
  },
  countText: {
    color: '#d9b061',
    fontSize: 22,
    fontWeight: 'bold',
  },
  countTextSelected: {
    color: '#2c1810',
  },
  hint: {
    color: '#888',
    fontSize: 12,
  },
  playerSection: {
    gap: 8,
    marginBottom: 10,
  },
  playerName: {
    fontSize: 14,
    fontWeight: '600',
  },
  humanName: {
    color: '#d9b061',
  },
  aiName: {
    color: '#888',
  },
  lordsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  lordCard: {
    width: '47%',
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: 'rgba(217,176,97,0.3)',
    padding: 10,
    gap: 4,
  },
  lordCardSelected: {
    borderColor: '#d9b061',
    backgroundColor: 'rgba(217,176,97,0.12)',
  },
  lordEmoji: {
    fontSize: 24,
  },
  lordName: {
    color: '#f5e6c8',
    fontSize: 13,
    fontWeight: '600',
  },
  lordNameSelected: {
    color: '#d9b061',
  },
  lordDesc: {
    color: '#999',
    fontSize: 10,
    lineHeight: 14,
  },
  aiLord: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: 8,
    padding: 10,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  aiLordIcon: {
    fontSize: 22,
  },
  aiLordText: {
    color: '#888',
    fontSize: 12,
  },
  startBtn: {
    backgroundColor: '#d9b061',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    marginTop: 10,
  },
  startText: {
    color: '#2c1810',
    fontSize: 18,
    fontWeight: 'bold',
  },
});
