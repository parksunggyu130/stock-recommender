from app.services import _simulate_virtual_portfolio, SIMULATION_SEED_KRW


def test_empty_results_returns_none():
    assert _simulate_virtual_portfolio([]) is None


def test_virtual_portfolio_profit_calculation():
    results = [
        {"ticker": "A", "name": "A사", "rec_price": 100000, "current_price": 120000, "change_pct": 20.0},
        {"ticker": "B", "name": "B사", "rec_price": 100000, "current_price": 100000, "change_pct": 0.0},
        {"ticker": "C", "name": "C사", "rec_price": 100000, "current_price": 90000, "change_pct": -10.0},
    ]

    sim = _simulate_virtual_portfolio(results)

    assert sim["seed"] == SIMULATION_SEED_KRW
    for holding in sim["holdings"]:
        assert holding["shares"] == 33  # floor(3,333,333.33 / 100,000)
        assert holding["cost"] == 3_300_000

    assert sim["final_value"] == 10_330_000
    assert sim["profit"] == 330_000
    assert sim["profit_pct"] == 3.3


def test_virtual_portfolio_handles_expensive_stock_leftover_cash():
    # 배분액보다 비싼 종목은 1주도 못 사고 현금으로 남는다
    results = [{"ticker": "X", "name": "X사", "rec_price": 50_000_000, "current_price": 60_000_000, "change_pct": 20.0}]

    sim = _simulate_virtual_portfolio(results)

    assert sim["holdings"][0]["shares"] == 0
    assert sim["final_value"] == SIMULATION_SEED_KRW
    assert sim["profit"] == 0
