import React from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';

interface Props {
  onBack: () => void;
}

const sections = [
  {
    title: '🎯 Amaç',
    content: 'İlk 10 Zafer Puanına (ZP) ulaşan oyuncu kazanır. Köy kurarak (+1 ZP), şehre yükselterek (+2 ZP), en büyük orduya ve en uzun yola sahip olarak puan kazanabilirsiniz.',
  },
  {
    title: '🎲 Tur Sırası',
    content: '1. Zar at\n2. Kaynak topla (zarın gösterdiği token\'lı bölgelerden)\n3. Yol / Köy / Şehir / Asker inşa et\n4. Ticaret yap\n5. Saldır (isteğe bağlı, turda 1 kez)\n6. Turu bitir',
  },
  {
    title: '🏗️ İnşa Maliyetleri',
    content: '🛤️ Yol: 1🌲 + 1⛰️\n🏘️ Köy: 1🌲 + 1⛰️ + 1🌾 + 1🐑\n🏰 Şehir: 2🌾 + 3⚒️\n⚔️ Asker: 1🐑 + 1🌾 + 1⚒️',
  },
  {
    title: '🦹 7 Atılırsa',
    content: '7\'den fazla kaynağı olan herkes yarısını kaybeder. Aktif oyuncu haydutları yeni bir bölgeye taşır ve komşu bir rakipten 1 kaynak çalar. Haydutun bulunduğu bölge üretim yapmaz.',
  },
  {
    title: '🔄 Ticaret',
    content: 'Banka ile 4:1 (veya liman bonuslarıyla 3:1 / 2:1) takas yapabilirsiniz. Ayrıca rakiplerle teklifler sunabilirsiniz.',
  },
  {
    title: '⚔️ Savaş',
    content: 'Saldırı = Asker sayısı + 1 + d6\nSavunma = (Şehir=2 / Köy=1) + sur bonusu + 1 + d6\n\nSaldırı kazanırsa: şehir→köy, köy→yok edilir. Kazanan kaynak yağmalar.',
  },
  {
    title: '🏆 Özel Ödüller',
    content: '🗡️ En Büyük Ordu: En az 3 askeri olan ve en fazla askere sahip oyuncu +2 ZP alır.\n🛤️ En Uzun Yol: En az 5 uzunlukta ve en uzun yola sahip oyuncu +2 ZP alır.',
  },
  {
    title: '👑 Lordlar',
    content: '🪙 Tüccar: 3:1 banka takas\n⚔️ Savaşçı: +2 ordu gücü\n🏰 Mimar: Yol için taş gerekmez\n🌿 Şifacı: Afet bağışıklığı',
  },
];

export function HowToPlayScreen({ onBack }: Props) {
  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={onBack} style={styles.backBtn}>
          <Text style={styles.backText}>← Geri</Text>
        </TouchableOpacity>
        <Text style={styles.title}>❓ Nasıl Oynanır</Text>
        <View style={{ width: 60 }} />
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        {sections.map((s) => (
          <View key={s.title} style={styles.section}>
            <Text style={styles.sectionTitle}>{s.title}</Text>
            <Text style={styles.sectionText}>{s.content}</Text>
          </View>
        ))}
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
  backBtn: { padding: 8 },
  backText: { color: '#d9b061', fontSize: 15 },
  title: { color: '#d9b061', fontSize: 18, fontWeight: 'bold' },
  content: { padding: 16, gap: 16, paddingBottom: 40 },
  section: {
    backgroundColor: 'rgba(44,24,16,0.8)',
    borderRadius: 10,
    padding: 14,
    borderLeftWidth: 3,
    borderLeftColor: '#d9b061',
  },
  sectionTitle: {
    color: '#d9b061',
    fontSize: 15,
    fontWeight: 'bold',
    marginBottom: 6,
  },
  sectionText: {
    color: '#f0ddc0',
    fontSize: 13,
    lineHeight: 20,
  },
});
