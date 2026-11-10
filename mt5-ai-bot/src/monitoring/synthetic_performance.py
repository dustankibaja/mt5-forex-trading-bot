"""Deterministic, synthetic-only replay with no terminal or journal input."""
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)


@dataclass(frozen=True)
class SyntheticQuote:
    utc_ms: int
    bid: Decimal
    ask: Decimal


@dataclass(frozen=True)
class SyntheticIntent:
    decision_id: str
    model: str
    decision_utc_ms: int
    direction: int
    units: int
    stop_distance: Decimal
    target_distance: Decimal
    slippage: Decimal
    round_trip_commission: Decimal
    opening_equity: Decimal


@dataclass(frozen=True)
class SyntheticResult:
    decision_id: str
    model: str
    entry_utc_ms: int
    entry: Decimal
    exit_utc_ms: int | None
    exit: Decimal | None
    exit_reason: str | None
    gross_pnl: Decimal | None
    net_pnl: Decimal | None
    swap: Decimal
    max_equity_drawdown: Decimal
    nominal_net_r: Decimal | None


def replay_synthetic(intent: SyntheticIntent, quotes: tuple[SyntheticQuote, ...],
                     *, swap_debits: tuple[tuple[int, Decimal], ...] = ()) -> SyntheticResult | None:
    """Replay one fixture from its immutable inputs, including after restart.

    Charges apply on timestamps strictly after entry through liquidation.
    Drawdown marks the open position at executable bid/ask and reserves fees.
    A stop crossed by a gap takes the worse observed price. A target receives
    at most the target, with adverse slippage on either type of exit.
    """
    if (type(intent) is not SyntheticIntent or not intent.decision_id or not intent.model
            or type(intent.decision_utc_ms) is not int or intent.decision_utc_ms < 0
            or type(intent.direction) is not int or intent.direction not in (-1, 0, 1)
            or type(intent.units) is not int or intent.units <= 0):
        raise ValueError("Invalid synthetic intent")
    positive = (intent.stop_distance, intent.target_distance, intent.opening_equity)
    costs = (intent.slippage, intent.round_trip_commission)
    if (any(not value.is_finite() or value <= ZERO for value in positive)
            or any(not value.is_finite() or value < ZERO for value in costs)):
        raise ValueError("Invalid synthetic costs, distances, or equity")
    previous = -1
    for quote in quotes:
        if (type(quote) is not SyntheticQuote or type(quote.utc_ms) is not int
                or quote.utc_ms <= previous or not quote.bid.is_finite() or not quote.ask.is_finite()
                or not ZERO < quote.bid <= quote.ask):
            raise ValueError("Expected chronological synthetic bid/ask fixtures")
        previous = quote.utc_ms
    if any(type(utc_ms) is not int or utc_ms < 0 or not debit.is_finite() or debit < ZERO
           for utc_ms, debit in swap_debits):
        raise ValueError("Expected nonnegative synthetic swap debits")
    prospective = tuple(q for q in quotes if q.utc_ms > intent.decision_utc_ms)
    if not prospective or intent.direction == 0:
        return None

    direction = intent.direction
    first = prospective[0]
    entry = (first.ask if direction > 0 else first.bid) + direction * intent.slippage
    stop = entry - direction * intent.stop_distance
    target = entry + direction * intent.target_distance
    if min(entry, stop, target) <= ZERO:
        raise ValueError("Synthetic protection prices must be positive")
    peak = intent.opening_equity
    drawdown = ZERO
    swap = ZERO
    for quote in prospective:
        swap = sum((debit for utc_ms, debit in swap_debits
                    if first.utc_ms < utc_ms <= quote.utc_ms), ZERO)
        executable = quote.bid if direction > 0 else quote.ask
        stop_hit = direction * (executable - stop) <= ZERO
        target_hit = direction * (executable - target) >= ZERO
        reference = target if target_hit else executable
        liquidation = reference - direction * intent.slippage
        gross = direction * (liquidation - entry) * intent.units
        net = gross - intent.round_trip_commission - swap
        equity = intent.opening_equity + net
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        if stop_hit or target_hit:
            return SyntheticResult(intent.decision_id, intent.model, first.utc_ms, entry,
                                   quote.utc_ms, liquidation, "stop" if stop_hit else "target",
                                   gross, net, swap, drawdown,
                                   net / (intent.stop_distance * intent.units))
    return SyntheticResult(intent.decision_id, intent.model, first.utc_ms, entry,
                           None, None, None, None, None, swap, drawdown, None)
