import asyncio
from sqlalchemy import select
from app.domain.models.product import Product
from app.analytics.repository import AnalyticsRepository
from app.sourcing.engine import SourcingEngine

# Use a throwaway approach: replicate using the test db? Hard here. Instead print rule thresholds from the engine's default config.
from app.sourcing.models import SourcingConfig
cfg = SourcingConfig()
print("min_roi", cfg.min_roi_percentage, "target_roi", cfg.target_roi_percentage)
print("min_profit", cfg.min_net_profit, "target_profit", cfg.target_net_profit)
print("min_sales", cfg.min_monthly_sales, "target_sales", cfg.target_monthly_sales)
print("max_new_sellers", cfg.max_new_sellers, "target_new_sellers", cfg.target_new_sellers, "min_new_sellers", cfg.min_new_sellers, "max_fba_pct", cfg.max_fba_percentage)
print("critical threshold", cfg.critical_rule_fail_threshold)
print("buy_box min win", cfg.min_buy_box_win_rate)
print("min opp score", cfg.minimum_opportunity_score)
