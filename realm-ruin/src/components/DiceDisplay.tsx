import React, { useEffect, useRef } from 'react';
import { Animated, StyleSheet, Text, View } from 'react-native';

const DOT_POSITIONS: Record<number, [number, number][]> = {
  1: [[1, 1]],
  2: [[0, 0], [2, 2]],
  3: [[0, 0], [1, 1], [2, 2]],
  4: [[0, 0], [2, 0], [0, 2], [2, 2]],
  5: [[0, 0], [2, 0], [1, 1], [0, 2], [2, 2]],
  6: [[0, 0], [2, 0], [0, 1], [2, 1], [0, 2], [2, 2]],
};

function Die({ value, animated }: { value: number; animated: boolean }) {
  const rotAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (animated) {
      rotAnim.setValue(0);
      Animated.timing(rotAnim, {
        toValue: 1,
        duration: 400,
        useNativeDriver: true,
      }).start();
    }
  }, [value, animated]);

  const spin = rotAnim.interpolate({
    inputRange: [0, 0.5, 1],
    outputRange: ['0deg', '180deg', '360deg'],
  });

  const positions = DOT_POSITIONS[value] ?? DOT_POSITIONS[1];

  return (
    <Animated.View style={[styles.die, animated && { transform: [{ rotate: spin }] }]}>
      <View style={styles.dotGrid}>
        {positions.map(([col, row], i) => (
          <View
            key={i}
            style={[
              styles.dot,
              {
                position: 'absolute',
                left: col * 10 + 4,
                top: row * 10 + 4,
              },
            ]}
          />
        ))}
      </View>
    </Animated.View>
  );
}

interface DiceDisplayProps {
  values: [number, number] | null;
  rolling?: boolean;
}

export function DiceDisplay({ values, rolling = false }: DiceDisplayProps) {
  const total = values ? values[0] + values[1] : null;
  const isHot = total === 6 || total === 8;
  const isSeven = total === 7;

  return (
    <View style={styles.container}>
      {values ? (
        <>
          <View style={styles.dice}>
            <Die value={values[0]} animated={rolling} />
            <Text style={styles.plus}>+</Text>
            <Die value={values[1]} animated={rolling} />
          </View>
          <Text style={[styles.total, isHot && styles.hot, isSeven && styles.seven]}>
            {total} {isSeven ? '🦹' : isHot ? '🔥' : ''}
          </Text>
        </>
      ) : (
        <View style={styles.dice}>
          <View style={[styles.die, styles.empty]}>
            <Text style={styles.emptyText}>?</Text>
          </View>
          <Text style={styles.plus}>+</Text>
          <View style={[styles.die, styles.empty]}>
            <Text style={styles.emptyText}>?</Text>
          </View>
        </View>
      )}
    </View>
  );
}

const CELL = 38;

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
  },
  dice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  die: {
    width: CELL,
    height: CELL,
    backgroundColor: '#f5e6c8',
    borderRadius: 6,
    borderWidth: 2,
    borderColor: '#d9b061',
    justifyContent: 'center',
    alignItems: 'center',
    position: 'relative',
  },
  empty: {
    backgroundColor: 'rgba(245, 230, 200, 0.2)',
  },
  emptyText: {
    color: '#d9b061',
    fontSize: 18,
    fontWeight: 'bold',
  },
  dotGrid: {
    width: 34,
    height: 34,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#2c1810',
  },
  plus: {
    color: '#d9b061',
    fontSize: 16,
    fontWeight: 'bold',
  },
  total: {
    color: '#f5e6c8',
    fontSize: 18,
    fontWeight: 'bold',
    marginTop: 4,
  },
  hot: {
    color: '#e74c3c',
  },
  seven: {
    color: '#e67e22',
  },
});
