import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { LogCategory, LogEntry } from '../game/types';

const CATEGORY_COLOR: Record<LogCategory, string> = {
  dice: '#3498db',
  build: '#2ecc71',
  combat: '#e74c3c',
  event: '#e67e22',
  trade: '#9b59b6',
  system: '#95a5a6',
};

interface EventLogProps {
  log: LogEntry[];
  maxHeight?: number;
}

export function EventLog({ log, maxHeight = 140 }: EventLogProps) {
  return (
    <View style={[styles.container, { maxHeight }]}>
      <Text style={styles.header}>📜 Vakayiname</Text>
      <ScrollView style={styles.scroll} nestedScrollEnabled>
        {log.slice(0, 30).map((entry) => (
          <View
            key={entry.id}
            style={[styles.entry, { borderLeftColor: CATEGORY_COLOR[entry.category] }]}
          >
            <Text style={styles.message}>{entry.message}</Text>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: 'rgba(44, 24, 16, 0.92)',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#d9b061',
    overflow: 'hidden',
  },
  header: {
    color: '#d9b061',
    fontSize: 12,
    fontWeight: 'bold',
    paddingHorizontal: 10,
    paddingTop: 6,
    paddingBottom: 4,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(217,176,97,0.3)',
  },
  scroll: {
    flex: 1,
  },
  entry: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderLeftWidth: 3,
    marginVertical: 1,
  },
  message: {
    color: '#f0ddc0',
    fontSize: 11,
    lineHeight: 15,
  },
});
