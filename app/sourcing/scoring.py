"""Sourcing Engine — Scoring Methodology v1.0.0

The sourcing engine evaluates products against 7 weighted rules to produce
an Opportunity Score (0-100), Confidence Level, and Risk Level. This document
describes the methodology in detail.

══════════════════════════════════════════════════════════════════════════════
SCORING METHODOLOGY
══════════════════════════════════════════════════════════════════════════════

1. OVERVIEW
──────────────────────────────────────────────────────────────────────────────

Each product is evaluated independently against 7 rules. Each rule produces:
- A normalized score (0.0–1.0)
- A pass/fail status against a minimum threshold
- A severity level (critical, major, minor, info)
- Human-readable reasoning

The Opportunity Score is the weighted average of all rule scores, scaled to 0-100.

    weighted_score = Σ(rule_score_i × weight_i) / Σ(weight_i)
    total_score = weighted_score × 100

2. RULE WEIGHTS (Default)
──────────────────────────────────────────────────────────────────────────────

    Rule                    Weight    Severity    Description
    ─────────────────────   ──────    ────────    ───────────────────────────
    Minimum ROI             0.25      Critical    Return on investment
    Minimum Profit          0.20      Critical    Net profit per unit
    Minimum Sales           0.15      Major       Monthly sales volume
    Competition Level       0.15      Major       Seller count & FBA saturation
    Buy Box Stability       0.10      Minor       Buy Box win rate
    Price Stability         0.08      Minor       Price coefficient of variation
    Inventory Availability  0.07      Major       Days of stock available
    ─────────────────────   ──────    ────────    ───────────────────────────
    Total                   1.00

3. NORMALIZATION FORMULA
──────────────────────────────────────────────────────────────────────────────

Each rule normalizes its observed value to a 0.0–1.0 score using:

    Below minimum:    score = actual / minimum × 0.5          (0.0 to 0.5)
    At minimum:       score = 0.5
    Between min/target: score = 0.5 + (actual-min)/(target-min) × 0.5
    At or above target: score = 1.0

This ensures:
- Below minimum always scores < 0.5 (failing range)
- At minimum scores exactly 0.5 (borderline)
- Above minimum scores > 0.5 (passing range)
- At target scores 1.0 (perfect)

4. RULE DETAILS
──────────────────────────────────────────────────────────────────────────────

4.1 Minimum ROI (Weight: 0.25, Severity: CRITICAL)
    Metric: ROI = (Net Profit / Total Cost) × 100
    Default minimum: 20%
    Default target: 50%
    Why: ROI measures return on capital. Low ROI means poor capital efficiency.

4.2 Minimum Profit (Weight: 0.20, Severity: CRITICAL)
    Metric: Net Profit per Unit = Amazon Price - Total Cost
    Default minimum: $2.00
    Default target: $10.00
    Why: Low-profit products are fragile — small price changes wipe out margins.

4.3 Minimum Sales (Weight: 0.15, Severity: MAJOR)
    Metric: Estimated Monthly Sales
    Default minimum: 300 units/month
    Default target: 2,000 units/month
    Why: Low-volume products may not justify the effort of listing and managing.

4.4 Competition Level (Weight: 0.15, Severity: MAJOR)
    Metrics: New seller count, FBA seller percentage
    Default: 1-20 sellers, <70% FBA
    Ideal: 3-10 sellers
    Why: Too few sellers = low demand. Too many = price wars.
          High FBA = Amazon dominance.

4.5 Buy Box Stability (Weight: 0.10, Severity: MINOR)
    Metric: Buy Box win rate percentage
    Default minimum: 60%
    Default target: 95%
    Why: Unstable Buy Box means aggressive repricing or seller churn.

4.6 Price Stability (Weight: 0.08, Severity: MINOR)
    Metric: Coefficient of Variation (CV) of Amazon price
    Default maximum: 15% CV
    Why: Volatile prices make profit forecasting unreliable.

4.7 Inventory Availability (Weight: 0.07, Severity: MAJOR)
    Metric: Days of stock = Available Quantity / Daily Sales Rate
    Default minimum: 30 days
    Default target: 90 days
    Why: Low stock means stockouts and lost ranking.

5. CONFIDENCE LEVEL
──────────────────────────────────────────────────────────────────────────────

Confidence is based on total historical data points available:

    Data Points    Confidence
    ───────────    ──────────
    500+           Very High
    200-499        High
    50-199         Medium
    10-49          Low
    <10            Very Low

6. RISK LEVEL
──────────────────────────────────────────────────────────────────────────────

Risk is determined by the Opportunity Score, elevated by rule failures:

    Score Range    Base Risk
    ───────────    ─────────
    85-100         Very Low
    70-84          Low
    50-69          Medium
    30-49          High
    0-29           Very High

    Risk is elevated by:
    - Any critical rule failure → Very High risk
    - 2+ major rule failures → High risk
    - 1 major rule failure → Elevate one level

7. VIABILITY
──────────────────────────────────────────────────────────────────────────────

A product is considered viable if:
    1. Critical rule failures < threshold (default: 1)
    2. Opportunity Score >= minimum (default: 40)

8. DATA SOURCES
──────────────────────────────────────────────────────────────────────────────

    Metric                    Source Table
    ─────────────────────     ─────────────────────────
    Amazon Price              amazon_prices
    Supplier Price            product_prices
    Seller Counts             seller_counts
    Sales Estimates           sales_estimates
    Amazon Fees               historical_fees
    Inventory                 historical_inventory
    Profit Calculations       profit_calculations

9. VERSION HISTORY
──────────────────────────────────────────────────────────────────────────────

    v1.0.0 (2025-07-31)  Initial methodology
"""
