"""Тесты для модуля сквозной диагностики пайплайна оплаты (services.payment_simulation)."""
import pytest
from services.payment_simulation import (
    run_payment_pipeline_simulation,
    format_simulation_report_html,
    PaymentSimulationReport,
    SimulationStepResult,
)
from db.connection import get_db


@pytest.mark.asyncio
async def test_run_payment_pipeline_simulation_structure():
    report = await run_payment_pipeline_simulation()

    assert isinstance(report, PaymentSimulationReport)
    assert len(report.steps) == 7
    step_ids = [s.step_id for s in report.steps]
    assert "db_order" in step_ids
    assert "platega_api" in step_ids
    assert "webhook_loopback" in step_ids
    assert "security_dedup" in step_ids
    assert "sub_profile" in step_ids
    assert "primary_node" in step_ids
    assert "secondary_sync" in step_ids

    for step in report.steps:
        assert isinstance(step, SimulationStepResult)
        assert step.status in ("ok", "warn", "fail")
        assert step.latency_ms >= 0
        assert step.details

    html = format_simulation_report_html(report)
    assert "Диагностика пайплайна оплаты" in html
    assert "База данных" in html
    assert "Тестовые записи автоматически вычищены" in html


@pytest.mark.asyncio
async def test_payment_simulation_cleans_up_records():
    report = await run_payment_pipeline_simulation()
    assert report is not None

    async with get_db() as db_conn:
        async with db_conn.execute("SELECT COUNT(*) FROM orders WHERE platega_tx_id LIKE 'sim_diag_%'") as cur:
            count_orders = (await cur.fetchone())[0]
        async with db_conn.execute("SELECT COUNT(*) FROM webhook_events WHERE tx_id LIKE 'sim_diag_%'") as cur:
            count_events = (await cur.fetchone())[0]

    assert count_orders == 0
    assert count_events == 0
