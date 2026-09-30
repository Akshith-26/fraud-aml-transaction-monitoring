"""
Transaction Fraud & AML Monitoring - end-to-end pipeline.

Steps
  1. Load the PaySim CSV into a local DuckDB database
  2. Profile fraud by transaction type and test the existing control (SQL)
  3. Apply 4 rule-based detection scenarios and measure precision / recall (SQL)
  4. Train an XGBoost model on days 1-20, test on days 21-30 (Python)
  5. Export an analyst alert queue + monitoring report to Excel
  6. Save charts to images/ and a results summary to outputs/

Run from the project root:
    python src/run_pipeline.py
"""
from pathlib import Path
import textwrap
import time

import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from xgboost import XGBClassifier
from sklearn.metrics import precision_score, recall_score, average_precision_score, confusion_matrix

from excel_utils import write_sheet

ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "data" / "raw" / "paysim.csv"
DB_PATH = ROOT / "data" / "fraud.duckdb"
SQL_DIR = ROOT / "sql"
OUT = ROOT / "outputs"
IMG = ROOT / "images"

TRAIN_LAST_STEP = 480          # hours 1-480 = days 1-20 for training, days 21-30 for testing
MODEL_THRESHOLD = 0.5
RULE_COLS = ["r1_account_drain", "r2_large_transfer", "r3_dest_mismatch", "r4_night_activity"]
FEATURES = ["amount", "oldbalanceorg", "newbalanceorig", "oldbalancedest", "newbalancedest",
            "err_orig", "err_dest", "is_transfer", "hour_of_day"]

plt.rcParams.update({"figure.dpi": 120, "axes.spines.top": False, "axes.spines.right": False,
                     "font.size": 10})


def fmt(v):
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, (float, np.floating)):
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"
    return str(v)


def to_md(df):
    """DataFrame -> markdown table (no extra dependency needed)."""
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(fmt(v) for v in row) + " |")
    return "\n".join(lines)


def sql(name):
    return (SQL_DIR / name).read_text()


def load_data(con):
    if not RAW_CSV.exists():
        raise FileNotFoundError(
            f"Missing {RAW_CSV}. Download the PaySim dataset from Kaggle and save the CSV "
            "as data/raw/paysim.csv (see data/README.md).")
    print("Loading PaySim CSV into DuckDB ...")
    src = f"read_csv_auto('{RAW_CSV.as_posix()}', header=true)"
    cols = con.execute(f"DESCRIBE SELECT * FROM {src}").df()["column_name"]
    select = ", ".join(f'"{c}" AS {c.lower()}' for c in cols)   # lower-case all column names
    con.execute(f"CREATE OR REPLACE TABLE transactions AS SELECT {select} FROM {src}")
    n = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    print(f"  {n:,} transactions loaded")
    return n


def run_sql_analysis(con):
    print("Running SQL analysis ...")
    profile = con.sql(sql("01_profile.sql")).df()
    control = con.sql(sql("02_existing_control.sql")).df()
    con.execute(sql("03_rules.sql"))
    rules = con.sql(sql("04_rule_performance.sql")).df()
    by_hour = con.sql(sql("05_fraud_by_hour.sql")).df()
    daily = con.sql(sql("06_daily_summary.sql")).df()
    return profile, control, rules, by_hour, daily


def train_model(con):
    print("Training XGBoost model (TRANSFER and CASH_OUT only) ...")
    df = con.sql("SELECT * FROM txn_flags WHERE type IN ('TRANSFER', 'CASH_OUT')").df()

    # Balance-error features: money that should have moved according to the ledger but didn't
    df["err_orig"] = df["newbalanceorig"] + df["amount"] - df["oldbalanceorg"]
    df["err_dest"] = df["oldbalancedest"] + df["amount"] - df["newbalancedest"]
    df["is_transfer"] = (df["type"] == "TRANSFER").astype(int)

    train = df[df["step"] <= TRAIN_LAST_STEP]
    test = df[df["step"] > TRAIN_LAST_STEP].copy()

    pos = max(int(train["isfraud"].sum()), 1)
    model = XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.1,
                          subsample=0.8, colsample_bytree=0.8, tree_method="hist",
                          scale_pos_weight=(len(train) - pos) / pos,
                          eval_metric="aucpr", random_state=42, n_jobs=-1)
    model.fit(train[FEATURES], train["isfraud"])

    test["risk_score"] = model.predict_proba(test[FEATURES])[:, 1]
    test["model_alert"] = (test["risk_score"] >= MODEL_THRESHOLD).astype(int)
    test["rules_hit"] = test[RULE_COLS].sum(axis=1)
    test["rule_alert"] = (test["rules_hit"] >= 2).astype(int)

    y = test["isfraud"]
    # The existing control applies to all transaction types, but it only ever fires on
    # TRANSFERs and all fraud is TRANSFER/CASH_OUT, so this subset gives the same result.
    comparison = []
    for name, pred in [("Existing control (>200k rule)", test["isflaggedfraud"]),
                       ("Combined SQL rules (2+ hit)", test["rule_alert"]),
                       ("XGBoost model", test["model_alert"])]:
        tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
        comparison.append({
            "approach": name, "alerts": int(pred.sum()), "true_positives": int(tp),
            "false_positives": int(fp), "missed_fraud": int(fn),
            "precision_pct": round(100 * precision_score(y, pred, zero_division=0), 2),
            "recall_pct": round(100 * recall_score(y, pred, zero_division=0), 2)})
    comparison = pd.DataFrame(comparison)
    pr_auc = average_precision_score(y, test["risk_score"]) if y.sum() else float("nan")

    importance = (pd.Series(model.feature_importances_, index=FEATURES)
                  .sort_values(ascending=False).rename("importance").reset_index()
                  .rename(columns={"index": "feature"}))
    return test, comparison, pr_auc, importance


def export_excel(profile, rules, comparison, daily, test):
    print("Writing Excel report ...")
    queue = (test[test["model_alert"] == 1]
             .sort_values("risk_score", ascending=False)
             [["day", "step", "type", "nameorig", "namedest", "amount", "oldbalanceorg",
               "newbalanceorig", "risk_score", "rules_hit"] + RULE_COLS + ["isfraud"]]
             .head(5000)
             .rename(columns={"isfraud": "confirmed_fraud (label)"}))
    money = {"amount": "#,##0.00", "oldbalanceorg": "#,##0.00", "newbalanceorig": "#,##0.00",
             "total_amount": "#,##0", "fraud_amount": "#,##0"}
    path = OUT / "fraud_monitoring_report.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        write_sheet(xw, queue, "Alert Queue", {**money, "risk_score": "0.000"},
                    color_scale_cols=["risk_score"])
        write_sheet(xw, comparison, "Rules vs Model")
        write_sheet(xw, rules, "Rule Performance (All)", {"alerts": "#,##0", "true_positives": "#,##0",
                    "false_positives": "#,##0"}, color_scale_cols=["precision_pct"], reverse_scale=True)
        write_sheet(xw, profile, "Fraud by Type", {**money, "transactions": "#,##0"})
        write_sheet(xw, daily, "Daily Summary", {**money, "transactions": "#,##0"})
    return path


def make_charts(profile, rules, by_hour, comparison, importance):
    print("Saving charts ...")
    navy, red, grey = "#1F3864", "#C0392B", "#B0B7C3"

    # 1. Fraud by transaction type
    fig, ax = plt.subplots(figsize=(7, 3.6))
    p = profile.sort_values("fraud_transactions")
    ax.barh(p["type"], p["fraud_transactions"], color=[red if v > 0 else grey for v in p["fraud_transactions"]])
    for i, v in enumerate(p["fraud_transactions"]):
        ax.text(v, i, f" {v:,.0f}", va="center")
    ax.set_title("Fraudulent transactions by type", loc="left", fontweight="bold")
    ax.set_xlabel("Fraud transactions")
    fig.tight_layout(); fig.savefig(IMG / "fraud_by_type.png"); plt.close(fig)

    # 2. Rule precision vs recall
    fig, ax = plt.subplots(figsize=(9, 4.2))
    r = rules.set_index("rule")
    x = np.arange(len(r))
    ax.bar(x - 0.2, r["precision_pct"].fillna(0), 0.4, label="Precision %", color=navy)
    ax.bar(x + 0.2, r["recall_pct"].fillna(0), 0.4, label="Recall %", color=red)
    ax.set_xticks(x, [textwrap.fill(s, 14) for s in r.index], fontsize=8)
    ax.set_ylabel("%"); ax.set_ylim(0, 105); ax.legend(frameon=False)
    ax.set_title("Detection rules: precision vs recall (all 30 days)", loc="left", fontweight="bold")
    fig.tight_layout(); fig.savefig(IMG / "rule_performance.png"); plt.close(fig)

    # 3. Fraud rate by hour
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.plot(by_hour["hour_of_day"], by_hour["fraud_rate_pct"], marker="o", color=red)
    ax.axvspan(-0.5, 5.5, color=grey, alpha=0.3, label="R4 window (00:00-05:59)")
    ax.set_xticks(range(0, 24, 2)); ax.set_xlabel("Hour of day"); ax.set_ylabel("Fraud rate %")
    ax.set_title("Fraud rate by hour (TRANSFER + CASH_OUT)", loc="left", fontweight="bold")
    ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(IMG / "fraud_rate_by_hour.png"); plt.close(fig)

    # 4. Existing control vs rules vs model (test period)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    c = comparison.set_index("approach")
    x = np.arange(len(c))
    ax.bar(x - 0.2, c["precision_pct"], 0.4, label="Precision %", color=navy)
    ax.bar(x + 0.2, c["recall_pct"], 0.4, label="Recall %", color=red)
    ax.set_xticks(x, [textwrap.fill(s, 16) for s in c.index], fontsize=8)
    ax.set_ylim(0, 105); ax.legend(frameon=False)
    ax.set_title("Test period (days 21-30): control vs rules vs model", loc="left", fontweight="bold")
    fig.tight_layout(); fig.savefig(IMG / "model_comparison.png"); plt.close(fig)

    # 5. Feature importance
    fig, ax = plt.subplots(figsize=(7, 3.6))
    imp = importance.sort_values("importance")
    ax.barh(imp["feature"], imp["importance"], color=navy)
    ax.set_title("XGBoost feature importance", loc="left", fontweight="bold")
    fig.tight_layout(); fig.savefig(IMG / "feature_importance.png"); plt.close(fig)


def write_summary(n_txn, control, rules, comparison, pr_auc, profile):
    ctrl = control.iloc[0]
    comb = rules[rules["rule"].str.startswith("Combined")].iloc[0]
    model = comparison[comparison["approach"] == "XGBoost model"].iloc[0]
    fraud_amt = profile["fraud_amount"].sum()
    best_single = rules[rules["rule"].str.startswith("R")].sort_values("recall_pct", ascending=False).iloc[0]

    text = f"""# Results summary (auto-generated by src/run_pipeline.py)

| Metric | Value |
|---|---|
| Transactions analyzed | {n_txn:,} |
| Fraudulent transactions | {int(ctrl.total_fraud):,} |
| Fraud amount | {fraud_amt:,.0f} |
| Existing control recall | {ctrl.recall_pct}% ({int(ctrl.true_positives):,} of {int(ctrl.total_fraud):,}) |
| Best single rule | {best_single.rule}: {best_single.recall_pct}% recall, {best_single.precision_pct}% precision |
| Combined rules (all 30 days) | {comb.recall_pct}% recall, {comb.precision_pct}% precision |
| XGBoost (test days 21-30) | {model.recall_pct}% recall, {model.precision_pct}% precision |
| XGBoost PR-AUC (test) | {pr_auc:.3f} |

### Rules vs model on the test period
{to_md(comparison)}

## Resume bullets (numbers filled in from this run)
- Developed 4 SQL-based fraud detection rules on {n_txn/1e6:.1f}M+ transactions, raising fraud recall from {ctrl.recall_pct}% (existing threshold control) to {comb.recall_pct}% with a combined rule set.
- Built an XGBoost fraud classifier trained on 20 days and validated on 10 held-out days, reaching {model.recall_pct}% recall at {model.precision_pct}% precision (PR-AUC {pr_auc:.2f}).
- Produced an Excel analyst alert queue and monitoring report tracking alert volume, precision, and recall by rule.
"""
    (OUT / "results_summary.md").write_text(text)
    return text


def update_readme(summary_text):
    """Replace the Results section of README.md with this run's numbers."""
    readme = ROOT / "README.md"
    start, end = "<!-- RESULTS_START -->", "<!-- RESULTS_END -->"
    text = readme.read_text()
    if start in text and end in text:
        body = summary_text.split("\n", 2)[2]   # drop the auto-generated title line
        body = body.split("## Resume bullets")[0].strip()
        new = text.split(start)[0] + start + "\n" + body + "\n" + end + text.split(end)[1]
        readme.write_text(new)


def main():
    t0 = time.time()
    OUT.mkdir(exist_ok=True); IMG.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    n_txn = load_data(con)
    profile, control, rules, by_hour, daily = run_sql_analysis(con)
    test, comparison, pr_auc, importance = train_model(con)

    for name, df in [("fraud_by_type", profile), ("rule_performance", rules),
                     ("fraud_by_hour", by_hour), ("daily_summary", daily),
                     ("rules_vs_model_test_period", comparison), ("feature_importance", importance)]:
        df.to_csv(OUT / f"{name}.csv", index=False)

    export_excel(profile, rules, comparison, daily, test)
    make_charts(profile, rules, by_hour, comparison, importance)
    summary = write_summary(n_txn, control, rules, comparison, pr_auc, profile)
    update_readme(summary)
    print("\n" + summary)
    con.close()
    print(f"Done in {time.time() - t0:.0f}s. See outputs/ and images/.")


if __name__ == "__main__":
    main()
