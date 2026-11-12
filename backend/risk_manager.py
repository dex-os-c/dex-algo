from typing import Dict, Any, List, Optional, Tuple
from config import get_config

# Exit evaluation tuple: (should_exit, reason, pnl)
Tuple_Exit = Tuple[bool, str, float]


class RiskManager:
    """
    Quantitative Risk Management & Position Sizing Engine.
    Enforces:
    - 1% Max Account Risk Per Trade
    - Volatility-adjusted share sizing via ATR
    - Maximum Open Positions Limit
    - Buying Power / Cash availability constraints
    - Maximum single-position capital allocation (25% cap)
    """
    def __init__(self):
        self.config = get_config()

    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        atr: float,
        equity: float,
        buying_power: float,
        cash: float,
        current_positions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        cfg = get_config()
        sym = symbol.upper()

        # 1. Max positions check
        if len(current_positions) >= cfg.MAX_POSITIONS:
            return {
                "approved": False,
                "shares": 0,
                "symbol": sym,
                "reason": f"Max open positions reached ({len(current_positions)}/{cfg.MAX_POSITIONS})"
            }

        # 2. Existing position check (prevent double exposure)
        for pos in current_positions:
            if pos.get("symbol", "").upper() == sym:
                return {
                    "approved": False,
                    "shares": 0,
                    "symbol": sym,
                    "reason": f"Position already exists for {sym}"
                }

        # 3. Capital & Risk calculation
        risk_per_trade_pct = cfg.RISK_PER_TRADE_PCT  # e.g. 0.01 (1%)
        total_risk_budget = equity * risk_per_trade_pct

        dollar_risk_per_share = max(0.01, atr * cfg.ATR_MULTIPLIER)
        raw_shares = int(total_risk_budget / dollar_risk_per_share)

        if raw_shares < 1:
            # Check if we can allocate at least 1 share within risk parameters
            if (entry_price * 1.0) <= (buying_power * 0.95):
                raw_shares = 1
            else:
                return {
                    "approved": False,
                    "shares": 0,
                    "symbol": sym,
                    "reason": f"Risk sizing yielded 0 shares (budget: ${total_risk_budget:.2f}, risk/sh: ${dollar_risk_per_share:.2f})"
                }

        # 4. Max Capital per single position cap (25% of equity)
        max_position_cost = equity * 0.25
        if (raw_shares * entry_price) > max_position_cost:
            raw_shares = max(1, int(max_position_cost / entry_price))

        # 5. Buying power constraint check (95% safety buffer)
        max_affordable_shares = int((buying_power * 0.95) / entry_price) if entry_price > 0 else 0
        final_shares = min(raw_shares, max_affordable_shares)

        if final_shares < 1:
            return {
                "approved": False,
                "shares": 0,
                "symbol": sym,
                "reason": f"Insufficient buying power (${buying_power:.2f}) for 1 share of {sym} at ${entry_price:.2f}"
            }

        total_cost = round(final_shares * entry_price, 2)
        actual_risk_amount = round(final_shares * dollar_risk_per_share, 2)

        stop_loss = round(entry_price - (cfg.ATR_MULTIPLIER * atr), 2)
        take_profit = round(entry_price + (cfg.TAKE_PROFIT_MULTIPLIER * atr), 2)

        return {
            "approved": True,
            "symbol": sym,
            "shares": final_shares,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "dollar_risk_per_share": round(dollar_risk_per_share, 2),
            "risk_amount": actual_risk_amount,
            "risk_pct_actual": round((actual_risk_amount / equity * 100.0) if equity > 0 else 0.0, 2),
            "total_cost": total_cost,
            "reason": f"Approved {final_shares} shares ({round(actual_risk_amount/equity*100, 2)}% capital risk)"
        }

    def should_exit_position(
        self,
        position: Dict[str, Any],
        current_price: float,
        strategy_signal: Optional[Dict[str, Any]] = None
    ) -> Tuple_Exit:
        """
        Evaluates whether an open position should be closed based on:
        - Stop Loss breach
        - Take Profit target achieved
        - Technical strategy SELL signal
        """
        avg_entry = float(position.get("avg_entry_price", position.get("current_price", current_price)))
        stop_loss = float(position.get("stop_loss", 0.0))
        take_profit = float(position.get("take_profit", 0.0))

        # Check Stop Loss
        if stop_loss > 0.0 and current_price <= stop_loss:
            pnl = round((current_price - avg_entry) * float(position.get("qty", 1)), 2)
            return True, f"STOP-LOSS triggered at ${current_price:.2f} (SL: ${stop_loss:.2f})", pnl

        # Check Take Profit
        if take_profit > 0.0 and current_price >= take_profit:
            pnl = round((current_price - avg_entry) * float(position.get("qty", 1)), 2)
            return True, f"TAKE-PROFIT triggered at ${current_price:.2f} (TP: ${take_profit:.2f})", pnl

        # Check Strategy Reversal Signal
        if strategy_signal and strategy_signal.get("signal") == "SELL":
            pnl = round((current_price - avg_entry) * float(position.get("qty", 1)), 2)
            return True, f"Strategy SELL exit: {strategy_signal.get('reason', 'reversal')}", pnl

        return False, "", 0.0


# Simple tuple return type helper
Tuple_Exit = tuple[bool, str, float]
