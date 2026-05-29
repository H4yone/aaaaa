import React, { useEffect, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { MainMenuScreen } from './src/screens/MainMenuScreen';
import { SetupScreen } from './src/screens/SetupScreen';
import { GameScreen } from './src/screens/GameScreen';
import { GameEndScreen } from './src/screens/GameEndScreen';
import { HowToPlayScreen } from './src/screens/HowToPlayScreen';
import { useGameStore } from './src/state/gameStore';
import { clearSave } from './src/state/persistence';

type Screen = 'menu' | 'setup' | 'game' | 'end' | 'howtoplay';

export default function App() {
  const [screen, setScreen] = useState<Screen>('menu');
  const { state: gs, initGame, loadSavedGame, checkSave } = useGameStore();

  useEffect(() => {
    checkSave();
  }, []);

  useEffect(() => {
    if (gs?.phase === 'ended' && screen === 'game') {
      setScreen('end');
    }
  }, [gs?.phase]);

  const handleContinue = async () => {
    await loadSavedGame();
    setScreen('game');
  };

  const handleStartGame = (playerCount: number, lordChoices: number[]) => {
    initGame(playerCount, lordChoices);
    setScreen('game');
  };

  const handleReplay = async () => {
    await clearSave();
    setScreen('menu');
  };

  const handleMenu = async () => {
    await clearSave();
    setScreen('menu');
  };

  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      {screen === 'menu' && (
        <MainMenuScreen
          onNewGame={() => setScreen('setup')}
          onContinue={handleContinue}
          onHowToPlay={() => setScreen('howtoplay')}
        />
      )}
      {screen === 'setup' && (
        <SetupScreen onStart={handleStartGame} onBack={() => setScreen('menu')} />
      )}
      {screen === 'game' && gs && <GameScreen />}
      {screen === 'end' && gs && (
        <GameEndScreen gs={gs} onReplay={handleReplay} onMenu={handleMenu} />
      )}
      {screen === 'howtoplay' && (
        <HowToPlayScreen onBack={() => setScreen('menu')} />
      )}
    </SafeAreaProvider>
  );
}
