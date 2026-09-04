package com.namuh.smarttrader;

import android.content.Context;
import android.content.SharedPreferences;

public final class BudgetStore {
    private static final String PREF = "namuh_budget";
    private static final String KEY_LIMIT = "daily_limit_won";
    private static final long DEFAULT_LIMIT = 200_000L;

    private final SharedPreferences prefs;

    public BudgetStore(Context context) {
        prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    public long loadLimitWon() {
        return prefs.getLong(KEY_LIMIT, DEFAULT_LIMIT);
    }

    public void saveLimitWon(long value) {
        prefs.edit().putLong(KEY_LIMIT, value).apply();
    }
}
