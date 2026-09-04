package com.namuh.smarttrader;

import android.content.Context;
import android.graphics.*;
import android.view.View;
import java.util.ArrayList;
import java.util.List;

/** 가벼운 미니 라인 차트. 외부 차트 라이브러리 없이 동작. */
public class SparklineView extends View {
    private final Paint linePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint gridPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private List<Double> points = new ArrayList<>();

    public SparklineView(Context context) {
        super(context);
        linePaint.setColor(Color.rgb(61, 104, 255));
        linePaint.setStrokeWidth(5f);
        linePaint.setStyle(Paint.Style.STROKE);
        linePaint.setStrokeCap(Paint.Cap.ROUND);
        linePaint.setStrokeJoin(Paint.Join.ROUND);
        gridPaint.setColor(Color.rgb(231, 235, 243));
        gridPaint.setStrokeWidth(1f);
    }

    public void setPoints(List<Double> values) {
        points = values == null ? new ArrayList<>() : new ArrayList<>(values);
        invalidate();
    }

    @Override protected void onDraw(Canvas c) {
        super.onDraw(c);
        float w = getWidth(), h = getHeight();
        c.drawLine(0, h * .5f, w, h * .5f, gridPaint);
        if (points.size() < 2) return;
        double min = Double.MAX_VALUE, max = -Double.MAX_VALUE;
        for (double v : points) { min = Math.min(min, v); max = Math.max(max, v); }
        if (max == min) max = min + 1;
        Path p = new Path();
        for (int i = 0; i < points.size(); i++) {
            float x = i * w / (points.size() - 1f);
            float y = (float)(h - ((points.get(i) - min) / (max - min)) * h);
            y = Math.max(3f, Math.min(h - 3f, y));
            if (i == 0) p.moveTo(x, y); else p.lineTo(x, y);
        }
        c.drawPath(p, linePaint);
    }
}
