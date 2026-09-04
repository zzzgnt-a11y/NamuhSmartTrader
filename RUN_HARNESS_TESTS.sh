#!/usr/bin/env bash
set -euo pipefail
OUT=.harness_classes
rm -rf "$OUT" && mkdir -p "$OUT"
javac -d "$OUT" \
  app/src/main/java/com/namuh/smarttrader/BudgetPolicy.java \
  app/src/main/java/com/namuh/smarttrader/Position.java \
  app/src/main/java/com/namuh/smarttrader/TradeRecord.java \
  app/src/main/java/com/namuh/smarttrader/PortfolioState.java \
  app/src/main/java/com/namuh/smarttrader/OrderGuard.java \
  app/src/main/java/com/namuh/smarttrader/PaperAccount.java \
  tools/BudgetPolicyHarness.java tools/PaperAccountHarness.java
java -cp "$OUT" com.namuh.smarttrader.BudgetPolicyHarness
java -cp "$OUT" com.namuh.smarttrader.PaperAccountHarness
