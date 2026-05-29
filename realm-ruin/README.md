# ⚔️ Realm & Ruin — Ortaçağ Strateji Oyunu

Catan'dan ilham alan, ortaçağ temalı, tek oyunculu (yapay zekâya karşı) mobil strateji oyunu.

## 🚀 Kurulum & Çalıştırma

```bash
cd realm-ruin
npm install
npx expo start
```

Expo Go uygulamasıyla QR kodu tarat veya `a` / `i` ile emülatörde aç.

## 📁 Proje Yapısı

```
src/
├── game/           # Saf TypeScript oyun mantığı (UI bağımsız)
│   ├── types.ts    # Tüm tip tanımları
│   ├── board.ts    # Hex tahta üretimi, vertex/edge hesaplamaları
│   ├── lords.ts    # Lord tanımları ve yetenek verileri
│   ├── rules.ts    # İnşa kuralları, mesafe kuralı, doğrulama
│   ├── resources.ts# Kaynak üretimi, takas, başlangıç kaynakları
│   ├── combat.ts   # Savaş çözümlemesi
│   ├── events.ts   # Rastgele olaylar
│   └── scoring.ts  # ZP, en uzun yol (DFS), en büyük ordu
├── ai/
│   └── ai.ts       # Yapay zeka tur mantığı, yerleştirme skorlaması
├── state/
│   ├── gameStore.ts    # Zustand store, tüm oyun aksiyonları
│   └── persistence.ts  # AsyncStorage kayıt/yükleme
├── screens/
│   ├── MainMenuScreen.tsx
│   ├── SetupScreen.tsx
│   ├── GameScreen.tsx
│   ├── GameEndScreen.tsx
│   └── HowToPlayScreen.tsx
└── components/
    ├── HexBoard.tsx    # react-native-svg ile hex tahta
    ├── ResourcePanel.tsx
    ├── DiceDisplay.tsx
    ├── PlayerList.tsx
    ├── EventLog.tsx
    ├── TradeModal.tsx
    └── OfferModal.tsx
```

## 🎮 Oyun Mekanikleri

- **Hex Tahta**: Klasik 3-4-5-4-3 dizilişiyle 19 altıgen
- **Lordlar**: Tüccar, Savaşçı, Mimar, Şifacı — her biri benzersiz pasif yetenek
- **Hazırlık**: Yılan (snake) düzeninde köy+yol yerleştirme
- **Tur**: Zar → Üretim → İnşa/Ticaret/Saldırı → Turu Bitir
- **Zafer Puanları**: Köy (1), Şehir (2), Büyük Ordu (+2), Uzun Yol (+2)
- **Savaş**: Zar + asker + lord bonusu ile çözümleme

## 🔧 Teknik Detaylar

- **React Native + Expo** (TypeScript)
- **Zustand** durum yönetimi
- **react-native-svg** hex tahta çizimi
- **AsyncStorage** kayıt sistemi
- Tamamen **offline** — backend yok

## 🛠️ Sonraki Geliştirmeler

1. Ses efektleri (expo-av)
2. Animasyonlu kaynak toplama (+kaynak yazıları)
3. Daha gelişmiş AI stratejisi (minimax)
4. Çevrimiçi çok oyunculu mod
5. Daha fazla lord ve özel etkinlikler
6. Başarım sistemi
