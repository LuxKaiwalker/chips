export type PlayerStatus = 'active' | 'folded' | 'all_in' | 'sitting_out' | 'busted'
export type RoomPhase = 'lobby' | 'in_hand' | 'between_hands'
export type Street = 'preflop' | 'flop' | 'turn' | 'river' | 'showdown'

export interface Player {
  seat_id: number
  display_name: string
  stack: number
  status: PlayerStatus
  connected: boolean
  contrib_street: number
  contrib_hand: number
  is_button: boolean
  sit_out_next: boolean
}

export interface Pot {
  label: string
  amount: number
  eligible_seats: number[]
}

export interface LegalActions {
  seat_id: number
  can_fold: boolean
  can_check: boolean
  can_call: boolean
  call_amount: number
  can_bet_or_raise: boolean
  action_label: 'bet' | 'raise'
  min_to: number | null
  max_to: number | null
}

export interface HandResult {
  reason: 'fold_out' | 'showdown'
  payouts: Record<string, number>
}

export interface HandState {
  hand_number: number
  button_seat: number
  street: Street
  current_bet: number
  to_act_seat: number | null
  pots: Pot[]
  total_pot: number
  legal_actions: LegalActions | null
  awaiting_runout_confirmation: boolean
  action_log: string[]
  last_result: HandResult | null
  concluded: boolean
}

export interface RoomConfig {
  small_blind: number
  big_blind: number
  starting_stack: number
  raise_presets: number[]
  rotate_dealer: boolean
}

export interface RoomState {
  code: string
  phase: RoomPhase
  host_seat_id: number
  current_dealer_seat: number
  config: RoomConfig
  players: Player[]
  hand: HandState | null
}

export const STREET_DEAL_LABEL: Record<Street, string> = {
  preflop: 'Preflop — deal 2 hole cards to each player',
  flop: 'Dealing the Flop',
  turn: 'Dealing the Turn',
  river: 'Dealing the River',
  showdown: 'Showdown — reveal hands',
}

export const STREET_CARD_COUNT: Record<Street, number> = {
  preflop: 0,
  flop: 3,
  turn: 4,
  river: 5,
  showdown: 5,
}
