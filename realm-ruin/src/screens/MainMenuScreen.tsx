import React, { useEffect, useState } from 'react';
import { Animated, Easing, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useGameStore } from '../state/gameStore';

interface Props {
  onNewGame: () => void;
  onContinue: () => void;
  onHowToPlay: () => void;
}

export function MainMenuScreen({ onNewGame, onContinue, onHowToPlay }: Props) {
  const { isSaveAvailable, checkSave } = useGameStore();
  const fadeAnim = React.useRef(new Animated.Value(0)).current;
  const titleAnim = React.useRef(new Animated.Value(-30)).current;

  useEffect(() => {
    checkSave();
    Animated.parallel([
      Animated.timing(fadeAnim, { toValue: 1, duration: 1000, useNativeDriver: true }),
      Animated.spring(titleAnim, { toValue: 0, useNativeDriver: true, tension: 50 }),
    ]).start();
  }, []);

  return (
    <View style={styles.container}>
      {/* Background decoration */}
      <View style={styles.bgOverlay} />

      <Animated.View
        style={[styles.content, { opacity: fadeAnim, transform: [{ translateY: titleAnim }] }]}
      >
        {/* Title */}
        <View style={styles.titleBlock}>
          <Text style={styles.titleSmall}>⚔️ ─── ⚔️</Text>
          <Text style={styles.title}>REALM</Text>
          <Text style={styles.titleAnd}>&</Text>
          <Text style={styles.title}>RUIN</Text>
          <Text style={styles.titleSmall}>🏰 Ortaçağ Strateji 🏰</Text>
        </View>

        {/* Buttons */}
        <View style={styles.buttons}>
          <MenuButton
            label="⚔️  Yeni Oyun"
            onPress={onNewGame}
            primary
          />

          {isSaveAvailable && (
            <MenuButton
              label="📜  Devam Et"
              onPress={onContinue}
            />
          )}

          <MenuButton
            label="❓  Nasıl Oynanır"
            onPress={onHowToPlay}
          />
        </View>

        <Text style={styles.footer}>v1.0 — Catan'dan ilham alındı</Text>
      </Animated.View>
    </View>
  );
}

function MenuButton({
  label,
  onPress,
  primary = false,
}: {
  label: string;
  onPress: () => void;
  primary?: boolean;
}) {
  return (
    <TouchableOpacity
      style={[styles.btn, primary && styles.btnPrimary]}
      onPress={onPress}
      activeOpacity={0.75}
    >
      <Text style={[styles.btnText, primary && styles.btnTextPrimary]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0905',
  },
  bgOverlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(44, 24, 16, 0.6)',
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  titleBlock: {
    alignItems: 'center',
    marginBottom: 50,
  },
  title: {
    fontSize: 56,
    fontWeight: '900',
    color: '#d9b061',
    letterSpacing: 10,
    textShadowColor: 'rgba(0,0,0,0.8)',
    textShadowOffset: { width: 2, height: 2 },
    textShadowRadius: 4,
  },
  titleAnd: {
    fontSize: 28,
    color: '#b08040',
    marginVertical: -6,
    fontStyle: 'italic',
  },
  titleSmall: {
    fontSize: 14,
    color: '#b08040',
    letterSpacing: 4,
    marginVertical: 6,
  },
  buttons: {
    width: '100%',
    maxWidth: 300,
    gap: 14,
    marginBottom: 40,
  },
  btn: {
    borderWidth: 2,
    borderColor: '#d9b061',
    borderRadius: 10,
    paddingVertical: 16,
    paddingHorizontal: 24,
    alignItems: 'center',
    backgroundColor: 'rgba(217, 176, 97, 0.08)',
  },
  btnPrimary: {
    backgroundColor: '#d9b061',
  },
  btnText: {
    color: '#d9b061',
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: 1,
  },
  btnTextPrimary: {
    color: '#2c1810',
  },
  footer: {
    color: '#5a4030',
    fontSize: 11,
  },
});
