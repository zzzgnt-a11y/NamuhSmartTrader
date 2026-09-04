package com.namuh.smarttrader;

import android.content.Context;
import android.graphics.Color;
import android.view.*;
import android.widget.*;
import java.util.List;

public class CandidateAdapter extends BaseAdapter {
    private final Context context;
    private List<StockCandidate> rows;
    private boolean smart;

    public CandidateAdapter(Context context, List<StockCandidate> rows, boolean smart) {
        this.context = context; this.rows = rows; this.smart = smart;
    }

    public void setRows(List<StockCandidate> rows, boolean smart) {
        this.rows = rows; this.smart = smart; notifyDataSetChanged();
    }

    @Override public int getCount() { return rows.size(); }
    @Override public Object getItem(int p) { return rows.get(p); }
    @Override public long getItemId(int p) { return p; }

    private TextView tv(String text, int sp, boolean bold) {
        TextView v = new TextView(context);
        v.setText(text);
        v.setTextSize(sp);
        v.setTextColor(Color.rgb(25,25,25));
        v.setPadding(0, 4, 0, 4);
        if (bold) v.setTypeface(null, android.graphics.Typeface.BOLD);
        return v;
    }

    @Override public View getView(int position, View convertView, ViewGroup parent) {
        StockCandidate x = rows.get(position);
        LinearLayout box = new LinearLayout(context);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(28, 20, 28, 20);

        LinearLayout top = new LinearLayout(context);
        top.setOrientation(LinearLayout.HORIZONTAL);
        TextView title = tv(x.name + "  " + x.code, 17, true);
        top.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        TextView badge = tv(String.format("%.1f점", x.score), 16, true);
        top.addView(badge);
        box.addView(top);

        box.addView(tv(smart ? x.subtitleSmart() : x.subtitleScalp(), 13, false));
        box.addView(tv(x.reasonText(), 12, false));

        View line = new View(context);
        line.setBackgroundColor(Color.rgb(230,230,230));
        box.addView(line, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1));
        return box;
    }
}
