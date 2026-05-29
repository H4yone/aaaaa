// ─── Resource & Lord ──────────────────────────────────────────────────────────

export type ResourceType = 'wood' | 'stone' | 'grain' | 'sheep' | 'iron';
export type TileResource = ResourceType | 'desert';

export type LordType = 'merchant' | 'warrior' | 'architect' | 'healer';

export interface Lord {
  type: LordType;
  name: string;
  description: string;
  emoji: string;
}

// ─── Board ────────────────────────────────────────────────────────────────────

export type PortType = '3:1' | 'wood2:1' | 'stone2:1' | 'grain2:1' | 'sheep2:1' | 'iron2:1';

export interface HexTile {
  id: number;         // 0-18
  resource: TileResource;
  token: number | null; // 2-12, null for desert
  row: number;
  col: number;
  cx: number;         // logical x coordinate (in units of R)
  cy: number;         // logical y coordinate (in units of R)
  hasRobber: boolean;
}

export interface Vertex {
  id: number;
  lx: number;          // logical x (in units of R)
  ly: number;          // logical y
  adjacentHexIds: number[];
  adjacentVertexIds: number[];
  adjacentEdgeIds: number[];
  portType: PortType | null;
}

export interface Edge {
  id: number;
  vertexIds: [number, number];
  adjacentHexIds: number[];
}

export interface Board {
  hexes: HexTile[];
  vertices: Vertex[];
  edges: Edge[];
  desertHexId: number;
}

// ─── Player ───────────────────────────────────────────────────────────────────

export type ResourceCounts = Record<ResourceType, number>;

export interface Player {
  id: number;
  name: string;
  lord: Lord;
  color: string;
  resources: ResourceCounts;
  soldiers: number;
  hasLargestArmy: boolean;
  hasLongestRoad: boolean;
  isAI: boolean;
}

// ─── Buildings / Roads ────────────────────────────────────────────────────────

export type BuildingType = 'village' | 'city';

export interface Building {
  vertexId: number;
  playerId: number;
  type: BuildingType;
}

export interface Road {
  edgeId: number;
  playerId: number;
}

// ─── Events & Log ─────────────────────────────────────────────────────────────

export type GameEventType = 'plague' | 'drought' | 'harvest' | 'dragon' | 'crusade' | 'caravan';

export interface GameEvent {
  type: GameEventType;
  emoji: string;
  title: string;
  description: string;
}

export type LogCategory = 'dice' | 'build' | 'combat' | 'event' | 'trade' | 'system';

export interface LogEntry {
  id: number;
  message: string;
  category: LogCategory;
  turn: number;
}

// ─── Trade ────────────────────────────────────────────────────────────────────

export interface TradeOffer {
  fromPlayerId: number;
  toPlayerId: number;
  give: Partial<ResourceCounts>;
  receive: Partial<ResourceCounts>;
}

// ─── Game Phase ───────────────────────────────────────────────────────────────

export type GamePhase = 'setup' | 'playing' | 'ended';
export type ActionPhase = 'preroll' | 'postroll' | 'robber';

export interface SetupState {
  order: number[];       // player indices in snake order
  step: number;          // current step in order (0 = first)
  round: 1 | 2;          // first or second placement round
  pendingRoad: boolean;  // waiting to place road after village
  lastVillageId: number | null;
}

// ─── Full Game State ──────────────────────────────────────────────────────────

export interface GameState {
  board: Board;
  players: Player[];
  buildings: Building[];
  roads: Road[];

  phase: GamePhase;
  setup: SetupState;
  currentPlayerIndex: number;
  actionPhase: ActionPhase;
  turnNumber: number;

  diceValues: [number, number] | null;
  lastEvent: GameEvent | null;
  pendingTradeOffer: TradeOffer | null;
  pendingRobberSteal: number | null; // target player id to steal from, -1 if no steal possible

  log: LogEntry[];
  winner: number | null;
  hasAttackedThisTurn: boolean;
}
