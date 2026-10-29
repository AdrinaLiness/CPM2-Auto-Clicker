package com.adrina.cpm2;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.annotation.SuppressLint;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.Point;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Display;
import android.view.Gravity;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * CPM2 AI Driver — ядро.
 * Вводит касания ПРЯМО В ИГРУ через dispatchGesture (это настоящие
 * системные касания, никакие скриншоты не нужны), умеет держать газ
 * одновременно с рулением (multi-stroke) и на Android 14+ ЗАПИСЫВАЕТ
 * касания игрока (setMotionEventSources), чтобы потом повторить их
 * идеально вплоть до миллисекунд.
 */
public class DriverService extends AccessibilityService {

    public static DriverService I;
    public interface Listener { void onSvcEvent(String json); }
    public static volatile Listener listener;

    public final Handler ui = new Handler(Looper.getMainLooper());
    private WindowManager wm;
    private View overlayBar;

    public int W = 1080, H = 2340;
    public String mode = "arrows";             // "arrows" | "wheel"
    public String fgPackage = "";              // приложение на переднем плане

    // --- удерживаемая педаль (между фазами) ---
    private GestureDescription.StrokeDescription pedalStroke;
    private String pedalName = null;
    private float pedalX, pedalY;
    private double wheelAngle = 0;             // текущий угол руля (радианы)
    private static final double MAX_WHEEL_RAD = Math.toRadians(130);

    // --- очередь фаз заезда ---
    private final java.util.ArrayDeque<JSONObject> queue = new java.util.ArrayDeque<>();
    private volatile boolean running = false;
    private volatile boolean stopRequested = false;
    private String runLabel = "";

    // --- запись касаний ---
    public volatile boolean recording = false;
    private volatile boolean replaying = false;
    private long recT0 = 0;
    private final java.util.Map<Integer, Long> recLastT = new java.util.HashMap<>();
    private final java.util.Map<Integer, Boolean> recDown = new java.util.HashMap<>();
    private JSONArray recRows = new JSONArray();

    private static final long CHUNK_MS = 25000;   // окно повтора ≤ 25 с
    private static final long REC_MAX_MS = 150000;

    // ============================================================ ЖИЗНЬ

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        I = this;
        refreshSize();
        try {
            SharedPreferences p = prefs();
            mode = p.getString("mode", "arrows");
        } catch (Exception ignored) {}
        buildOverlay();
        enableMotionRecording();
        emit(ev("connected"));
        toast("CPM2 AI Driver: сервис подключён");
    }

    @Override
    public boolean onUnbind(Intent intent) {
        I = null;
        return super.onUnbind(intent);
    }

    @Override
    public void onDestroy() {
        I = null;
        super.onDestroy();
    }

    @Override
    public void onConfigurationChanged(android.content.res.Configuration cfg) {
        super.onConfigurationChanged(cfg);
        ui.postDelayed(new Runnable() { @Override public void run() { refreshSize(); } }, 300);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent e) {
        if (e == null) return;
        CharSequence pkg = e.getPackageName();
        if (pkg != null && e.getEventType() == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            String np = String.valueOf(pkg);
            if (!np.equals(fgPackage)) {
                fgPackage = np;
                emitQuiet(J(ev("foreground"), "pkg", np));
            }
        }
    }

    @Override
    public void onInterrupt() { }

    // ============================================================ СЕРВИС-ИНФО

    private void enableMotionRecording() {
        // Запись касаний из ЛЮБОГО приложения — Android 14 (API 34)+.
        if (Build.VERSION.SDK_INT >= 34) {
            try {
                android.accessibilityservice.AccessibilityServiceInfo info = getServiceInfo();
                if (info != null) {
                    info.setMotionEventSources(InputDevice.SOURCE_TOUCHSCREEN);
                    setServiceInfo(info);
                    emitQuiet(J(ev("recording_supported"), "ok", true));
                } else {
                    emitQuiet(J(ev("recording_supported"), "ok", false));
                }
            } catch (Throwable t) {
                emitQuiet(J(ev("recording_supported"), "ok", false));
            }
        } else {
            emitQuiet(J(ev("recording_supported"), "ok", false));
        }
    }

    public boolean recordingSupported() {
        return Build.VERSION.SDK_INT >= 34 && I != null;
    }

    private void refreshSize() {
        try {
            Display d = ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay();
            Point pt = new Point();
            d.getRealSize(pt);
            if (pt.x > 0 && pt.y > 0) { W = pt.x; H = pt.y; }
        } catch (Exception ignored) {}
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("cpm2", MODE_PRIVATE);
    }

    // ============================================================ КООРДИНАТЫ

    /** Позиция органа управления в пикселях (хранится в процентах экрана). */
    public float[] ctl(String name) {
        try {
            JSONObject cs = new JSONObject(prefs().getString("controls", "{}"));
            JSONObject c = cs.optJSONObject(name);
            if (c != null) {
                return new float[]{ (float)(c.getDouble("x") / 100.0 * W),
                                    (float)(c.getDouble("y") / 100.0 * H) };
            }
        } catch (Exception ignored) {}
        switch (name) { // разумные дефолты раскладки «кнопки»
            case "gas":     return new float[]{ W * 0.87f, H * 0.78f };
            case "brake":   return new float[]{ W * 0.87f, H * 0.92f };
            case "left":    return new float[]{ W * 0.09f, H * 0.85f };
            case "right":   return new float[]{ W * 0.27f, H * 0.85f };
            case "reverse": return new float[]{ W * 0.74f, H * 0.64f };
            case "wheel":   return new float[]{ W * 0.18f, H * 0.80f };
        }
        return new float[]{ W / 2f, H / 2f };
    }

    public float wheelRadius() {
        try {
            JSONObject cs = new JSONObject(prefs().getString("controls", "{}"));
            JSONObject c = cs.optJSONObject("wheel");
            if (c != null && c.has("r")) return (float)(c.getDouble("r") / 100.0 * Math.min(W, H));
        } catch (Exception ignored) {}
        return Math.min(W, H) * 0.10f;
    }

    // ============================================================ ПУТИ

    private static Path line(float x, float y) {
        Path p = new Path();
        p.moveTo(x, y);
        p.lineTo(x + 0.1f, y);
        return p;
    }

    private static Path arcPath(float cx, float cy, float r, double a0, double a1, int steps) {
        Path p = new Path();
        double from = Math.min(a0, a1), to = Math.max(a0, a1);
        boolean rev = a1 < a0;
        for (int i = 0; i <= steps; i++) {
            double t = from + (to - from) * i / steps;
            double a = rev ? (to - (t - from)) : t;
            float x = (float)(cx + r * Math.cos(a));
            float y = (float)(cy + r * Math.sin(a));
            if (i == 0) p.moveTo(x, y); else p.lineTo(x, y);
        }
        return p;
    }

    private static Path tapPath(float x, float y) {
        Path p = new Path();
        p.moveTo(x, y);
        p.lineTo(x + 0.1f, y);
        return p;
    }

    private static GestureDescription.StrokeDescription SD(Path path, long start, long dur, boolean cont) {
        if (Build.VERSION.SDK_INT >= 26) {
            return new GestureDescription.StrokeDescription(path, start, dur, cont);
        }
        return new GestureDescription.StrokeDescription(path, start, dur);
    }

    private static GestureDescription.StrokeDescription CONT(GestureDescription.StrokeDescription s,
                                                            Path path, long start, long dur, boolean cont) {
        if (Build.VERSION.SDK_INT >= 26) {
            try { return s.continueStroke(path, start, dur, cont); } catch (Throwable ignored) {}
        }
        return SD(path, start, dur, cont);
    }

    // ============================================================ ЗАЕЗД (ФАЗЫ)

    public boolean startManeuver(String phasesJson, String label) {
        if (I == null) return false;
        try {
            JSONArray arr = new JSONArray(phasesJson);
            if (arr.length() == 0) return false;
            stopAll(true);
            stopRequested = false;
            queue.clear();
            for (int i = 0; i < arr.length(); i++) queue.add(arr.getJSONObject(i));
            runLabel = label == null ? "заезд" : label;
            running = true;
            emit(J(J(ev("run_start"), "label", runLabel), "steps", queue.size()));
            ui.postDelayed(new Runnable() { @Override public void run() { step(); } }, 120);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private void step() {
        if (!running || stopRequested) return;
        if (queue.isEmpty()) { finishRun(); return; }
        JSONObject ph = queue.poll();
        try {
            long ms = clamp(ph.optLong("ms", 1000), 100, CHUNK_MS);
            String pedal = ph.has("pedal") && !ph.isNull("pedal") ? ph.getString("pedal") : null;
            if (pedal != null && (pedal.length() == 0 || "none".equals(pedal))) pedal = null;

            boolean willCont = false;
            if (pedal != null && !queue.isEmpty()) {
                JSONObject nx = queue.peek();
                String np = nx.has("pedal") && !nx.isNull("pedal") ? nx.getString("pedal") : null;
                willCont = pedal.equals(np);
            }

            GestureDescription.Builder b = new GestureDescription.Builder();

            // --- педаль ---
            if (pedal != null) {
                float[] p = ctl(pedal);
                if (pedalStroke != null && pedal.equals(pedalName)) {
                    pedalStroke = CONT(pedalStroke, line(pedalX, pedalY), 0, ms, willCont);
                    b.addStroke(pedalStroke);
                } else {
                    if (pedalStroke != null) { // сменили педаль: сначала отпустить
                        b.addStroke(CONT(pedalStroke, line(pedalX, pedalY), 0, 30, false));
                    }
                    pedalX = p[0]; pedalY = p[1]; pedalName = pedal;
                    pedalStroke = SD(line(p[0], p[1]), 0, ms, willCont);
                    b.addStroke(pedalStroke);
                }
            } else if (pedalStroke != null) {
                b.addStroke(CONT(pedalStroke, line(pedalX, pedalY), 0, 30, false));
                pedalStroke = null; pedalName = null;
            }

            // --- руление ---
            if (ph.has("steer") && !ph.isNull("steer")) {
                float s = (float) ph.getDouble("steer");
                s = Math.max(-1f, Math.min(1f, s));
                if ("wheel".equals(mode)) {
                    float[] c = ctl("wheel");
                    double a0 = wheelAngle;
                    double a1 = a0 + s * MAX_WHEEL_RAD;
                    b.addStroke(SD(arcPath(c[0], c[1], wheelRadius(), a0, a1, 24), 0, ms, false));
                    wheelAngle = a1;
                } else {
                    float[] p = ctl(s < 0 ? "left" : "right");
                    b.addStroke(SD(line(p[0], p[1]), 0, ms, false));
                }
            }

            // --- разовый тап (например, кнопка реверса) ---
            String tap = ph.has("tap") && !ph.isNull("tap") ? ph.getString("tap") : null;
            if (tap != null && tap.length() > 0) {
                float[] p = ctl(tap);
                b.addStroke(SD(tapPath(p[0], p[1]), 0, 90, false));
            }

            emit(J(J(ev("phase"), "left", queue.size() + 1), "note", ph.optString("note", "")));
            final long fms = ms;
            dispatchGesture(b.build(), new GestureResultCallback() {
                @Override public void onCompleted(GestureDescription g) {
                    ui.postDelayed(new Runnable() { @Override public void run() { step(); } }, 60);
                }
                @Override public void onCancelled(GestureDescription g) {
                    if (!stopRequested && running) {
                        ui.postDelayed(new Runnable() { @Override public void run() { step(); } }, 120);
                    }
                }
            }, ui);
        } catch (Exception ex) {
            emit(J(ev("error"), "msg", "фаза: " + ex.getMessage()));
            finishRun();
        }
    }

    private void finishRun() {
        running = false;
        releasePedal();
        emit(J(ev("run_done"), "label", runLabel));
    }

    private void releasePedal() {
        if (pedalStroke != null) {
            try {
                GestureDescription.Builder b = new GestureDescription.Builder();
                b.addStroke(CONT(pedalStroke, line(pedalX, pedalY), 0, 30, false));
                dispatchGesture(b.build(), new GestureResultCallback() {
                    @Override public void onCompleted(GestureDescription g) { }
                    @Override public void onCancelled(GestureDescription g) { }
                }, ui);
            } catch (Throwable ignored) {}
        }
        pedalStroke = null;
        pedalName = null;
        wheelAngle = 0;
    }

    public void stopAll() { stopAll(false); }

    public void stopAll(boolean silent) {
        stopRequested = true;
        running = false;
        replaying = false;
        queue.clear();
        // cancelGesture() в публичном API нет: новый dispatch отменяет текущий.
        // releasePedal шлёт короткий штрих — он и отменяет заезд, и отпускает газ.
        ui.postDelayed(new Runnable() {
            @Override public void run() { releasePedal(); }
        }, 80);
        if (!silent) emit(ev("run_stop"));
    }

    public boolean isRunning() { return running || replaying; }

    // ============================================================ ЗАПИСЬ

    public void startRecording() {
        if (!recordingSupported()) { emit(J(ev("error"), "msg", "Запись работает только на Android 14+")); return; }
        stopAll(true);
        recRows = new JSONArray();
        recLastT.clear();
        recDown.clear();
        recT0 = SystemClock.uptimeMillis();
        recording = true;
        emit(ev("record_start"));
        toast("ЗАПИСЬ касаний включена — веди машину!");
    }

    /** Останавливает запись и возвращает JSON потока касаний. */
    public String stopRecording() {
        if (!recording) return null;
        recording = false;
        long dur = SystemClock.uptimeMillis() - recT0;
        JSONObject out = new JSONObject();
        try {
            out.put("w", W);
            out.put("h", H);
            out.put("dur", dur);
            out.put("pts", recRows);
        } catch (Exception ignored) {}
        emit(J(J(ev("record_stop"), "dur", dur), "rows", recRows.length()));
        return out.toString();
    }

    @SuppressLint("NewApi")
    @Override
    public void onMotionEvent(MotionEvent e) {
        // API 34+: наблюдаем ВСЕ касания экрана, включая игру.
        if (I == null || !recording || replaying) return;
        try {
            if (e.getEventTime() < lastOverlayTap + 350) return; // свой тап по оверлею
            int action = e.getActionMasked();
            long t = e.getEventTime() - recT0;
            if (e.getY() < H * 0.12f) return;           // не пишем зону оверлея/статуса
            if (t > REC_MAX_MS) { stopRecording(); return; }

            if (action == MotionEvent.ACTION_DOWN) {
                addRow(e, 0, t, true);
                recDown.put(e.getPointerId(0), true);
            } else if (action == MotionEvent.ACTION_POINTER_DOWN) {
                int i = e.getActionIndex();
                addRow(e, i, t, true);
                recDown.put(e.getPointerId(i), true);
            } else if (action == MotionEvent.ACTION_MOVE) {
                for (int i = 0; i < e.getPointerCount(); i++) {
                    int id = e.getPointerId(i);
                    if (recDown.containsKey(id)) addRow(e, i, t, false);
                }
            } else if (action == MotionEvent.ACTION_POINTER_UP) {
                int i = e.getActionIndex();
                int id = e.getPointerId(i);
                addRow(e, i, t, true);
                recDown.remove(id);
            } else if (action == MotionEvent.ACTION_UP) {
                addRow(e, 0, t, true);
                recDown.remove(e.getPointerId(0));
            } else if (action == MotionEvent.ACTION_CANCEL) {
                stopRecording();
            }
        } catch (Throwable ignored) {}
    }

    private void addRow(MotionEvent e, int idx, long t, boolean force) {
        int id = e.getPointerId(idx);
        Long last = recLastT.get(id);
        if (!force && last != null && t - last < 33) return; // прореживание ~30 Гц
        recLastT.put(id, t);
        JSONObject row = new JSONObject();
        try {
            row.put("p", id);
            row.put("t", t);
            row.put("x", Math.round(e.getX(idx) * 10) / 10.0);
            row.put("y", Math.round(e.getY(idx) * 10) / 10.0);
        } catch (Exception ignored) {}
        recRows.put(row);
    }

    // ============================================================ ПОВТОР ЗАПИСИ

    public boolean startReplay(String recJson, String label) {
        if (I == null) return false;
        try {
            stopAll(true);
            stopRequested = false;
            final JSONObject rec = new JSONObject(recJson);
            final JSONArray pts = rec.getJSONArray("pts");
            final double rw = rec.getDouble("w"), rh = rec.getDouble("h");
            final long dur = rec.getLong("dur");
            if (pts.length() < 2) return false;

            replaying = true;
            emit(J(J(ev("replay_start"), "dur", dur), "label", label == null ? "повтор" : label));

            // точки каждого пальца
            final java.util.Map<Integer, JSONArray> byId = new java.util.HashMap<>();
            final java.util.Map<Integer, Long> upAt = new java.util.HashMap<>();
            for (int i = 0; i < pts.length(); i++) {
                JSONObject r = pts.getJSONObject(i);
                int pid = r.getInt("p");
                JSONArray arr = byId.get(pid);
                if (arr == null) { arr = new JSONArray(); byId.put(pid, arr); }
                arr.put(r);
                if (r.optBoolean("up", false)) upAt.put(pid, r.getLong("t"));
            }
            final long total = Math.max(dur, 1);
            if ((W != (int) rw && W != (int) rh) || (H != (int) rh && H != (int) rw)) {
                emit(J(ev("error"), "msg", "Ориентация экрана изменилась с момента записи — перезапиши заезд"));
                return false;
            }
            final java.util.Map<Integer, GestureDescription.StrokeDescription> carry =
                    new java.util.HashMap<>();
            final java.util.Map<Integer, float[]> lastPt = new java.util.HashMap<>(); // конец пути каждого пальца
            final int[] winIdx = { 0 };

            class Win implements Runnable {
                @Override public void run() {
                    if (!replaying) return;
                    long ws = winIdx[0] * CHUNK_MS;
                    long we = Math.min(ws + CHUNK_MS, total);
                    if (ws >= total) {
                        replaying = false;
                        emit(J(ev("run_done"), "label", "повтор завершён"));
                        return;
                    }
                    GestureDescription.Builder b = new GestureDescription.Builder();
                    try {
                        for (java.util.Map.Entry<Integer, JSONArray> en : byId.entrySet()) {
                            int pid = en.getKey();
                            JSONArray arr = en.getValue();
                            if (upAt.containsKey(pid) && upAt.get(pid) <= ws) continue;
                            // точки внутри окна
                            JSONArray in = new JSONArray();
                            long firstT = -1, lastT = -1;
                            JSONObject first = null, last = null;
                            for (int i = 0; i < arr.length(); i++) {
                                JSONObject r = arr.getJSONObject(i);
                                long t = r.getLong("t");
                                if (t >= ws && t <= we) {
                                    in.put(r);
                                    if (firstT < 0) { firstT = t; first = r; }
                                    lastT = t; last = r;
                                }
                            }
                            GestureDescription.StrokeDescription car = carry.get(pid);
                            if (first == null && car == null) continue;
                            float[] lastPoint = lastPt.get(pid);
                            Path path = new Path();
                            long startOff, durMs;
                            boolean willCont;
                            if (car != null && lastPoint != null) {
                                // продолжение штриха: путь обязан начинаться там,
                                // где закончился предыдущий
                                float nx = first != null ? (float)(first.getDouble("x") / rw * W) : lastPoint[0];
                                float ny = first != null ? (float)(first.getDouble("y") / rh * H) : lastPoint[1];
                                path.moveTo(lastPoint[0], lastPoint[1]);
                                path.lineTo(nx, ny);
                                if (first != null) {
                                    for (int i = 1; i < in.length(); i++) {
                                        JSONObject r = in.getJSONObject(i);
                                        path.lineTo((float)(r.getDouble("x") / rw * W),
                                                    (float)(r.getDouble("y") / rh * H));
                                    }
                                }
                                startOff = 0;
                                durMs = Math.max(30, (first != null ? lastT : we) - ws);
                                willCont = (first == null) || (lastT >= we && !upAt.containsKey(pid));
                            } else {
                                path.moveTo((float)(first.getDouble("x") / rw * W),
                                            (float)(first.getDouble("y") / rh * H));
                                for (int i = 1; i < in.length(); i++) {
                                    JSONObject r = in.getJSONObject(i);
                                    path.lineTo((float)(r.getDouble("x") / rw * W),
                                                (float)(r.getDouble("y") / rh * H));
                                }
                                startOff = Math.max(0, firstT - ws);
                                durMs = Math.max(30, lastT - firstT);
                                willCont = lastT >= we && !upAt.containsKey(pid);
                            }
                            GestureDescription.StrokeDescription sd;
                            if (car != null && Build.VERSION.SDK_INT >= 26) {
                                sd = CONT(car, path, startOff, durMs, willCont);
                            } else {
                                sd = SD(path, startOff, durMs, willCont);
                            }
                            if (willCont) {
                                carry.put(pid, sd);
                                float lx, ly;
                                if (first != null) {
                                    lx = (float)(last.getDouble("x") / rw * W);
                                    ly = (float)(last.getDouble("y") / rh * H);
                                } else if (lastPoint != null) {
                                    lx = lastPoint[0]; ly = lastPoint[1];
                                } else {
                                    lx = lastPoint != null ? lastPoint[0] : 0f;
                                    ly = lastPoint != null ? lastPoint[1] : 0f;
                                }
                                lastPt.put(pid, new float[]{ lx, ly });
                            } else {
                                carry.remove(pid);
                                lastPt.remove(pid);
                            }
                            b.addStroke(sd);
                        }
                        if (b.build().getStrokeCount() == 0) {
                            winIdx[0]++;
                            ui.post(winRun);
                            return;
                        }
                        final long fwe = we;
                        dispatchGesture(b.build(), new GestureResultCallback() {
                            @Override public void onCompleted(GestureDescription g) {
                                winIdx[0] = (int)(fwe / CHUNK_MS);
                                ui.post(winRun);
                            }
                            @Override public void onCancelled(GestureDescription g) {
                                if (!stopRequested && replaying) {
                                    winIdx[0] = (int)(fwe / CHUNK_MS);
                                    ui.postDelayed(winRun, 120);
                                }
                            }
                        }, ui);
                    } catch (Exception ex) {
                        replaying = false;
                        carry.clear();
                        emit(J(ev("error"), "msg", "повтор: " + ex.getMessage()));
                    }
                }
                Runnable winRun = this;
            }
            ui.postDelayed(new Win(), 150);
            return true;
        } catch (Exception e) {
            emit(J(ev("error"), "msg", "повтор: " + e.getMessage()));
            replaying = false;
            return false;
        }
    }

    // ============================================================ ОВЕРЛЕЙ

    @SuppressLint("ClickableViewAccessibility")
    private void buildOverlay() {
        if (overlayBar != null) return;
        try {
            wm = (WindowManager) getSystemService(WINDOW_SERVICE);
            LinearLayout bar = new LinearLayout(this);
            bar.setOrientation(LinearLayout.HORIZONTAL);
            bar.setBackgroundColor(0xD30E141F);
            GradientDrawable bg = new GradientDrawable();
            bg.setColor(0xD30E141F);
            bg.setCornerRadius(36f);
            bar.setBackground(bg);
            bar.setPadding(14, 8, 14, 8);
            bar.setAlpha(0.92f);

            bar.addView(ovBtn("\u25B6", 0xFF2E9E4F, new View.OnClickListener() {
                @Override public void onClick(View v) {
                    lastUiTap();
                    emit(J(ev("overlay"), "act", "start"));
                }
            }));
            bar.addView(ovBtn("\u23F9", 0xFF444E60, new View.OnClickListener() {
                @Override public void onClick(View v) {
                    lastUiTap();
                    stopAll(false);
                }
            }));
            bar.addView(ovBtn("\u2713", 0xFF1F7A33, new View.OnClickListener() {
                @Override public void onClick(View v) {
                    lastUiTap();
                    emit(J(ev("overlay"), "act", "success"));
                    toast("Победа отмечена — решение сохранено");
                }
            }));
            bar.addView(ovBtn("\u2715", 0xFF8C2B2B, new View.OnClickListener() {
                @Override public void onClick(View v) {
                    lastUiTap();
                    emit(J(ev("overlay"), "act", "fail"));
                }
            }));

            WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                    WindowManager.LayoutParams.WRAP_CONTENT,
                    WindowManager.LayoutParams.WRAP_CONTENT,
                    WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                            | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                    PixelFormat.TRANSLUCENT);
            lp.gravity = Gravity.TOP | Gravity.END;
            lp.x = 24;
            lp.y = 40;
            wm.addView(bar, lp);
            overlayBar = bar;
        } catch (Throwable t) {
            overlayBar = null;
        }
    }

    private long lastOverlayTap = 0; // тап по оверлею не должен попадать в запись

    private void lastUiTap() { lastOverlayTap = SystemClock.uptimeMillis(); }

    private Button ovBtn(String label, int color, View.OnClickListener cb) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextColor(Color.WHITE);
        b.setTextSize(16);
        b.setTypeface(null, Typeface.BOLD);
        b.setAllCaps(false);
        b.setMinWidth(96);
        b.setMinHeight(20);
        b.setPadding(18, 6, 18, 6);
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(26f);
        b.setBackground(g);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(6, 0, 6, 0);
        b.setLayoutParams(lp);
        b.setOnClickListener(cb);
        return b;
    }

    public void setOverlayVisible(final boolean vis) {
        ui.post(new Runnable() {
            @Override public void run() {
                try {
                    if (overlayBar == null) {
                        if (vis) buildOverlay();
                        return;
                    }
                    overlayBar.setVisibility(vis ? View.VISIBLE : View.GONE);
                } catch (Throwable ignored) {}
            }
        });
    }

    public boolean overlayVisible() {
        return overlayBar != null && overlayBar.getVisibility() == View.VISIBLE;
    }

    // ============================================================ УТИЛИТЫ

    public void setMode(String m) {
        mode = "wheel".equals(m) ? "wheel" : "arrows";
        prefs().edit().putString("mode", mode).apply();
        emitQuiet(J(ev("mode"), "mode", mode));
    }

    public void setControls(String json) {
        prefs().edit().putString("controls", json).apply();
    }

    public String getControls() {
        return prefs().getString("controls", "{}");
    }

    public boolean svcEnabledFor(String self) {
        try {
            String s = android.provider.Settings.Secure.getString(
                    getContentResolver(), android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
            return s != null && s.toLowerCase().contains("com.adrina.cpm2");
        } catch (Exception e) { return false; }
    }

    public AccessibilityNodeInfo root() { return getRootInActiveWindow(); }

    private static long clamp(long v, long lo, long hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    }

    private JSONObject ev(String type) {
        JSONObject o = new JSONObject();
        try { o.put("type", type); } catch (Exception ignored) {}
        return o;
    }

    /** put без JSONException — для цепочек логов. */
    private static JSONObject J(JSONObject o, String k, Object v) {
        try { o.put(k, v); } catch (Exception ignored) {}
        return o;
    }

    private void emit(JSONObject o) {
        Listener l = listener;
        if (l != null) { try { l.onSvcEvent(o.toString()); } catch (Throwable ignored) {} }
    }

    private void emitQuiet(JSONObject o) { emit(o); }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }
}
