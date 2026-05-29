import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Dimensions, GestureResponderEvent, PanResponder, ScrollView, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, G, Line, Polygon, Text as SvgText } from 'react-native-svg';
import { BOARD_LOGICAL_H, BOARD_LOGICAL_W, pipCount, toPixel } from '../game/board';
import { Board, Building, Edge, GameState, HexTile, Player, Road, Vertex } from '../game/types';
import { validAttackTargets, validCityUpgrades, validRoadPlacements, validVillagePlacements } from '../game/rules';

const { width: SCREEN_W } = Dimensions.get('window');

// Compute hex size to fit screen
const PADDING = 16;
const HEX_SIZE = Math.floor((SCREEN_W - PADDING * 2) / BOARD_LOGICAL_W);

// Logical board center offset (so all coords are positive)
const OFFSET_X = HEX_SIZE * 0.1;
const OFFSET_Y = HEX_SIZE * 1.1;

const SQ3 = Math.sqrt(3);

function lx2px(lx: number): number {
  return lx * HEX_SIZE + OFFSET_X;
}
function ly2px(ly: number): number {
  return ly * HEX_SIZE + OFFSET_Y;
}

// Vertex positions of a pointy-top hex at center (cx,cy) in logical units
const VOFF: [number, number][] = [
  [0, -1], [SQ3 / 2, -0.5], [SQ3 / 2, 0.5], [0, 1], [-SQ3 / 2, 0.5], [-SQ3 / 2, -0.5],
];

function hexPolygon(cx: number, cy: number): string {
  return VOFF.map(([dx, dy]) => `${lx2px(cx + dx)},${ly2px(cy + dy)}`).join(' ');
}

// ─── Colors ───────────────────────────────────────────────────────────────────

const RESOURCE_COLOR: Record<string, string> = {
  wood: '#2d6a1f',
  stone: '#7a7a7a',
  grain: '#d4a017',
  sheep: '#7ab648',
  iron: '#8b5e3c',
  desert: '#c2a46e',
};

const RESOURCE_ICON: Record<string, string> = {
  wood: '🌲',
  stone: '⛰️',
  grain: '🌾',
  sheep: '🐑',
  iron: '⚒️',
  desert: '🏜️',
};

const TOKEN_COLORS: Record<number, string> = {
  6: '#e74c3c', 8: '#e74c3c',
};

// ─── Main Component ───────────────────────────────────────────────────────────

interface HexBoardProps {
  gs: GameState;
  mode: 'setup_village' | 'setup_road' | 'place_village' | 'place_road' | 'place_city' | 'robber' | 'attack' | 'view';
  onVertexPress?: (vertexId: number) => void;
  onEdgePress?: (edgeId: number) => void;
  onHexPress?: (hexId: number) => void;
}

export function HexBoard({ gs, mode, onVertexPress, onEdgePress, onHexPress }: HexBoardProps) {
  const { board, buildings, roads, currentPlayerIndex, players, setup } = gs;

  // Compute which vertices/edges/hexes are highlighted based on mode
  const validVertices = useMemo<Set<number>>(() => {
    const pid = currentPlayerIndex;
    if (mode === 'setup_village') {
      const valids = validVillagePlacements(buildings, roads, board, pid, false);
      return new Set(valids);
    }
    if (mode === 'place_village') {
      return new Set(validVillagePlacements(buildings, roads, board, pid, true));
    }
    if (mode === 'place_city') {
      return new Set(validCityUpgrades(buildings, pid));
    }
    if (mode === 'attack') {
      return new Set(validAttackTargets(buildings, board, pid).map((b) => b.vertexId));
    }
    return new Set();
  }, [mode, buildings, roads, board, currentPlayerIndex]);

  const validEdges = useMemo<Set<number>>(() => {
    const pid = currentPlayerIndex;
    if (mode === 'setup_road') {
      const adjVid = gs.setup?.lastVillageId ?? undefined;
      return new Set(validRoadPlacements(roads, buildings, board, pid, adjVid));
    }
    if (mode === 'place_road') {
      return new Set(validRoadPlacements(roads, buildings, board, pid));
    }
    return new Set();
  }, [mode, roads, buildings, board, currentPlayerIndex, gs.setup?.lastVillageId]);

  const validHexes = useMemo<Set<number>>(() => {
    if (mode !== 'robber') return new Set();
    return new Set(board.hexes.filter((h) => !h.hasRobber).map((h) => h.id));
  }, [mode, board]);

  const boardH = ly2px(BOARD_LOGICAL_H) + OFFSET_Y;
  const boardW = lx2px(BOARD_LOGICAL_W) + OFFSET_X;

  return (
    <ScrollView
      horizontal
      style={{ flex: 1 }}
      contentContainerStyle={{ minWidth: boardW }}
      scrollEnabled={mode === 'view'}
    >
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ minHeight: boardH }}
        scrollEnabled={mode === 'view'}
      >
        <Svg width={boardW} height={boardH}>
          {/* Hex tiles */}
          {board.hexes.map((hex) => (
            <HexTileComp
              key={hex.id}
              hex={hex}
              highlighted={validHexes.has(hex.id)}
              onPress={onHexPress}
            />
          ))}

          {/* Roads */}
          {roads.map((road) => (
            <RoadComp key={road.edgeId} road={road} board={board} players={players} />
          ))}

          {/* Edge highlights (for road placement) */}
          {mode !== 'view' &&
            [...validEdges].map((eid) => (
              <EdgeHighlight
                key={eid}
                edgeId={eid}
                board={board}
                onPress={onEdgePress}
              />
            ))}

          {/* Buildings */}
          {buildings.map((building) => (
            <BuildingComp
              key={`${building.vertexId}-${building.playerId}`}
              building={building}
              board={board}
              players={players}
              highlighted={validVertices.has(building.vertexId)}
              onPress={onVertexPress}
            />
          ))}

          {/* Vertex highlights (for building placement) */}
          {mode !== 'view' &&
            [...validVertices]
              .filter((vid) => !buildings.some((b) => b.vertexId === vid))
              .map((vid) => (
                <VertexHighlight
                  key={vid}
                  vertexId={vid}
                  board={board}
                  onPress={onVertexPress}
                />
              ))}
        </Svg>
      </ScrollView>
    </ScrollView>
  );
}

// ─── Hex Tile ─────────────────────────────────────────────────────────────────

function HexTileComp({
  hex,
  highlighted,
  onPress,
}: {
  hex: HexTile;
  highlighted: boolean;
  onPress?: (id: number) => void;
}) {
  const pts = hexPolygon(hex.cx, hex.cy);
  const px = lx2px(hex.cx);
  const py = ly2px(hex.cy);
  const color = RESOURCE_COLOR[hex.resource];
  const pips = hex.token ? pipCount(hex.token) : 0;
  const tokenColor = hex.token && TOKEN_COLORS[hex.token] ? TOKEN_COLORS[hex.token] : '#2c1810';

  return (
    <G onPress={highlighted ? () => onPress?.(hex.id) : undefined}>
      <Polygon
        points={pts}
        fill={highlighted ? `${color}cc` : color}
        stroke={highlighted ? '#f1c40f' : '#2c1810'}
        strokeWidth={highlighted ? 3 : 1.5}
      />
      {/* Resource icon */}
      <SvgText
        x={px}
        y={py - HEX_SIZE * 0.18}
        textAnchor="middle"
        fontSize={HEX_SIZE * 0.42}
        fill="white"
      >
        {RESOURCE_ICON[hex.resource]}
      </SvgText>

      {/* Token circle */}
      {hex.token && (
        <>
          <Circle
            cx={px}
            cy={py + HEX_SIZE * 0.28}
            r={HEX_SIZE * 0.22}
            fill="#f5e6c8"
            stroke={tokenColor}
            strokeWidth={1.5}
          />
          <SvgText
            x={px}
            y={py + HEX_SIZE * 0.28 + HEX_SIZE * 0.08}
            textAnchor="middle"
            fontSize={HEX_SIZE * 0.2}
            fontWeight="bold"
            fill={tokenColor}
          >
            {hex.token}
          </SvgText>
          {/* Pip dots */}
          {Array.from({ length: pips }).map((_, i) => (
            <Circle
              key={i}
              cx={px - (pips - 1) * 3 + i * 6}
              cy={py + HEX_SIZE * 0.47}
              r={2}
              fill={tokenColor}
            />
          ))}
        </>
      )}

      {/* Robber */}
      {hex.hasRobber && (
        <SvgText
          x={px}
          y={py + HEX_SIZE * 0.15}
          textAnchor="middle"
          fontSize={HEX_SIZE * 0.35}
          fill="#000"
        >
          🦹
        </SvgText>
      )}
    </G>
  );
}

// ─── Road ─────────────────────────────────────────────────────────────────────

function RoadComp({
  road,
  board,
  players,
}: {
  road: Road;
  board: Board;
  players: Player[];
}) {
  const edge = board.edges[road.edgeId];
  if (!edge) return null;
  const [v1, v2] = edge.vertexIds;
  const v1d = board.vertices[v1];
  const v2d = board.vertices[v2];

  return (
    <Line
      x1={lx2px(v1d.lx)}
      y1={ly2px(v1d.ly)}
      x2={lx2px(v2d.lx)}
      y2={ly2px(v2d.ly)}
      stroke={players[road.playerId]?.color ?? '#fff'}
      strokeWidth={HEX_SIZE * 0.12}
      strokeLinecap="round"
    />
  );
}

// ─── Edge Highlight ───────────────────────────────────────────────────────────

function EdgeHighlight({
  edgeId,
  board,
  onPress,
}: {
  edgeId: number;
  board: Board;
  onPress?: (id: number) => void;
}) {
  const edge = board.edges[edgeId];
  if (!edge) return null;
  const [v1, v2] = edge.vertexIds;
  const v1d = board.vertices[v1];
  const v2d = board.vertices[v2];
  const mx = (lx2px(v1d.lx) + lx2px(v2d.lx)) / 2;
  const my = (ly2px(v1d.ly) + ly2px(v2d.ly)) / 2;

  return (
    <G onPress={() => onPress?.(edgeId)}>
      <Line
        x1={lx2px(v1d.lx)}
        y1={ly2px(v1d.ly)}
        x2={lx2px(v2d.lx)}
        y2={ly2px(v2d.ly)}
        stroke="#f1c40f"
        strokeWidth={HEX_SIZE * 0.1}
        strokeDasharray="4,4"
        opacity={0.8}
      />
      <Circle cx={mx} cy={my} r={HEX_SIZE * 0.18} fill="#f1c40f" opacity={0.6} />
    </G>
  );
}

// ─── Building ─────────────────────────────────────────────────────────────────

function BuildingComp({
  building,
  board,
  players,
  highlighted,
  onPress,
}: {
  building: Building;
  board: Board;
  players: Player[];
  highlighted: boolean;
  onPress?: (id: number) => void;
}) {
  const vertex = board.vertices[building.vertexId];
  if (!vertex) return null;

  const px = lx2px(vertex.lx);
  const py = ly2px(vertex.ly);
  const color = players[building.playerId]?.color ?? '#fff';
  const size = HEX_SIZE * (building.type === 'city' ? 0.25 : 0.2);

  return (
    <G onPress={() => onPress?.(building.vertexId)}>
      {building.type === 'city' ? (
        <>
          <Polygon
            points={`${px},${py - size * 1.6} ${px - size},${py} ${px + size},${py}`}
            fill={color}
            stroke={highlighted ? '#f1c40f' : '#2c1810'}
            strokeWidth={highlighted ? 2.5 : 1.5}
          />
          <Polygon
            points={`${px - size * 0.6},${py} ${px - size * 0.6},${py + size} ${px + size * 0.6},${py + size} ${px + size * 0.6},${py}`}
            fill={color}
            stroke={highlighted ? '#f1c40f' : '#2c1810'}
            strokeWidth={highlighted ? 2.5 : 1.5}
          />
        </>
      ) : (
        <Polygon
          points={`${px},${py - size * 1.5} ${px - size},${py + size * 0.5} ${px + size},${py + size * 0.5}`}
          fill={color}
          stroke={highlighted ? '#f1c40f' : '#2c1810'}
          strokeWidth={highlighted ? 2.5 : 1.5}
        />
      )}

      {/* Port indicator */}
      {vertex.portType && (
        <Circle
          cx={px + size}
          cy={py - size}
          r={HEX_SIZE * 0.1}
          fill="#d9b061"
          stroke="#2c1810"
          strokeWidth={1}
        />
      )}
    </G>
  );
}

// ─── Vertex Highlight ─────────────────────────────────────────────────────────

function VertexHighlight({
  vertexId,
  board,
  onPress,
}: {
  vertexId: number;
  board: Board;
  onPress?: (id: number) => void;
}) {
  const vertex = board.vertices[vertexId];
  if (!vertex) return null;

  const px = lx2px(vertex.lx);
  const py = ly2px(vertex.ly);

  return (
    <G onPress={() => onPress?.(vertexId)}>
      <Circle
        cx={px}
        cy={py}
        r={HEX_SIZE * 0.22}
        fill="#f1c40f"
        opacity={0.7}
        stroke="#2c1810"
        strokeWidth={1.5}
      />
    </G>
  );
}
