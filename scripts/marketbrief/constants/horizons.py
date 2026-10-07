"""Names of the horizon list and the horizon labels (core/horizons.py; docs/SPEC.md F2.7, decision 37)."""

FILE_STRATEGIES_CONFIG = "strategies.yaml"     # under config/ (W1's registry holds the horizon list)
KEY_HORIZONS, KEY_AI_HORIZONS = "horizons", "ai_horizons"

# Labels (marketbrief/contracts/horizons.py HORIZON_LABELS): every new row is n_plus_k; old rows are labelled on read.
LABEL_N_PLUS_K = "n_plus_k"
LABEL_LEGACY_CC = "legacy_cc"
LABEL_LEGACY_5D_D4 = "legacy_5d_d4"
HORIZON_LABELS = (LABEL_N_PLUS_K, LABEL_LEGACY_CC, LABEL_LEGACY_5D_D4)
COL_HORIZON_LABEL, COL_ENTRY_DATE, COL_EXIT_DATE = "horizon_label", "entry_date", "exit_date"

# The same rule as core.horizons.legacy_label, for SQL: the label of a row read from a kind.
SQL_LABEL_RANGES = f"coalesce(horizon_label, '{LABEL_LEGACY_CC}')"
SQL_LABEL_MODEL_SCORES = (f"coalesce(horizon_label, CASE WHEN horizon_days = 1 THEN '{LABEL_N_PLUS_K}' "
                          f"ELSE '{LABEL_LEGACY_5D_D4}' END)")

MSG_BAD_HORIZONS = ("config/strategies.yaml `{key}` must be a non-empty ascending list of distinct whole numbers "
                    ">= 1 (got {values!r})")
DESCRIPTION_N_PLUS_K = ("buy at the open of D (the first session after the as-of close), sell at the close of the "
                        "k-th session after D (N+k, decision 37)")
