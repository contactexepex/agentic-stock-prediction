"""Constants of the fundamentals collector (SEC XBRL company facts): periodic forms, concepts and period lengths."""
COLLECTOR_FUNDAMENTALS = "fundamentals"
PERIODIC_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A", "10-KT", "10-KT/A"}
USD, PER_SHARE, SHARES = "USD", "USD/shares", "shares"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
DEFAULT_NAMESPACE = "us-gaap"
DAYS_PER_YEAR = 365.25
DEFAULT_HISTORY_YEARS = 3
DEFAULT_RECHECK_DAYS = 10

# period lengths in days (inclusive): quarter (16-week quarters included), year to date, annual
QUARTER_DAYS = (70, 130)
YTD_DAYS = (150, 300)
ANNUAL_DAYS = (340, 380)
YEAR_AGO_DAYS = (357, 371)   # a period end this far before a known period end is one fiscal year earlier
PERIOD_INSTANT, PERIOD_QUARTER, PERIOD_YTD, PERIOD_ANNUAL = "instant", "quarter", "ytd", "annual"
FISCAL_ANNUAL, FISCAL_Q4 = "FY", "Q4"
YTD_LABELS = {"Q2": "H1", "Q3": "9M"}
ERROR_TEXT_LIMIT = 200

# concept -> (unit, tags in priority order). "dei:" marks a dei tag, others are us-gaap.
# Revenue: banks report net revenue (net of interest expense) as their headline; `Revenues`
# (total revenues) ranks above revenue from contracts with customers, which for some companies
# (banks, oil majors, GM) is only a part of total revenue.
CONCEPTS: dict[str, tuple[str, list[str]]] = {
    "revenue": (USD, ["RevenuesNetOfInterestExpense", "Revenues",
                      "RevenueFromContractWithCustomerExcludingAssessedTax",
                      "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                      "SalesRevenueGoodsNet"]),
    "cost_of_revenue": (USD, ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]),
    "gross_profit": (USD, ["GrossProfit"]),
    "operating_income": (USD, ["OperatingIncomeLoss"]),
    "net_income": (USD, ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"]),
    "eps_diluted": (PER_SHARE, ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]),
    "operating_cash_flow": (USD, ["NetCashProvidedByUsedInOperatingActivities",
                                  "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]),
    "capex": (USD, ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                    "PaymentsToAcquireOtherPropertyPlantAndEquipment"]),
    "cash": (USD, ["CashAndCashEquivalentsAtCarryingValue", "CashAndDueFromBanks", "Cash",
                   "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    # Debt parts; the fundamentals_debt view adds them up into total debt.
    "debt_combined": (USD, ["DebtLongtermAndShorttermCombinedAmount"]),
    "debt_long_term_total": (USD, ["LongTermDebt",
                                   "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"]),
    "debt_noncurrent": (USD, ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"]),
    "debt_current": (USD, ["DebtCurrent"]),
    "long_term_debt_current": (USD, ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"]),
    "short_term_borrowings": (USD, ["ShortTermBorrowings", "CommercialPaper", "OtherShortTermBorrowings"]),
    "shares_outstanding": (SHARES, ["dei:EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"]),
    "shares_diluted_avg": (SHARES, ["WeightedAverageNumberOfDilutedSharesOutstanding"]),
}
