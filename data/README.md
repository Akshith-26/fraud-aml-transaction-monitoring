# Data

This project uses the **PaySim synthetic financial dataset** (about 6.3M mobile-money transactions over 30 days).

1. Go to Kaggle and search for **"Synthetic Financial Datasets For Fraud Detection"** (PaySim, by ealaxi).
2. Download and unzip it.
3. Rename the CSV to `paysim.csv` and place it here: `data/raw/paysim.csv`.

The raw file (about 470 MB) is excluded from Git via `.gitignore`.

| Column | Meaning |
|---|---|
| step | Hour of the simulation (1-744 = 30 days) |
| type | PAYMENT, TRANSFER, CASH_OUT, CASH_IN, DEBIT |
| amount | Transaction amount |
| nameOrig / nameDest | Sender / receiver account IDs |
| oldbalanceOrg / newbalanceOrig | Sender balance before / after |
| oldbalanceDest / newbalanceDest | Receiver balance before / after |
| isFraud | 1 = fraudulent (the label) |
| isFlaggedFraud | 1 = flagged by the existing control (transfers over 200,000) |
