package com.adrina.cpm2;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.Settings;
import android.view.View;
import android.view.Window;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends Activity {

    private WebView web;
    private static MainActivity act;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        act = this;
        Window w = getWindow();
        w.addFlags(android.view.WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
        w.setStatusBarColor(0xFF0D111C);
        w.setNavigationBarColor(0xFF0D111C);

        // Android 13+: разрешение на уведомления — в рантайм
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{ Manifest.permission.POST_NOTIFICATIONS }, 41);
            }
        }
        makeChannel();

        web = new WebView(this);
        web.setBackgroundColor(0xFF0D111C);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setTextZoom(100);
        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage m) {
                android.util.Log.d("CPM2JS", m.message());
                return true;
            }
        });
        web.addJavascriptInterface(new Bridge(), "CPM2");
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        setContentView(web);
        web.loadUrl("file:///android_asset/cpm2.html");

        DriverService.listener = new DriverService.Listener() {
            @Override
            public void onSvcEvent(final String json) {
                if (web == null) return;
                web.post(new Runnable() {
                    @Override
                    public void run() {
                        if (web != null) {
                            web.evaluateJavascript(
                                "window.__svcEvent && window.__svcEvent(" +
                                JSONObject.quote(json) + ");", null);
                        }
                    }
                });
            }
        };
    }

    @Override
    protected void onDestroy() {
        act = null;
        DriverService.listener = null;
        super.onDestroy();
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    private void makeChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel("driver",
                    "AI-драйвер", NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("Ход заездов AI-драйвера");
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(ch);
        }
    }

    // ============================================================ BRIDGE

    private class Bridge {

        @JavascriptInterface
        public String status() {
            JSONObject o = new JSONObject();
            try {
                o.put("svc", DriverService.I != null);
                o.put("sdk", Build.VERSION.SDK_INT);
                o.put("recSupported", DriverService.I != null && DriverService.I.recordingSupported());
                o.put("mode", DriverService.I != null ? DriverService.I.mode : "arrows");
                o.put("overlay", DriverService.I != null && DriverService.I.overlayVisible());
                o.put("screenW", DriverService.I != null ? DriverService.I.W : 0);
                o.put("screenH", DriverService.I != null ? DriverService.I.H : 0);
                o.put("fg", DriverService.I != null ? DriverService.I.fgPackage : "");
                o.put("running", DriverService.I != null && DriverService.I.isRunning());
            } catch (Exception ignored) {}
            return o.toString();
        }

        @JavascriptInterface
        public void openAccessSettings() {
            try {
                startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            } catch (Exception e) {
                toast("Не удалось открыть настройки доступности");
            }
        }

        /** Открывает игру; пробует известные пакеты CPM2, возвращает имя найденного. */
        @JavascriptInterface
        public String launchGame(String candidatesJson) {
            try {
                JSONArray arr = new JSONArray(candidatesJson);
                PackageManager pm = getPackageManager();
                for (int i = 0; i < arr.length(); i++) {
                    String pkg = arr.getString(i).trim();
                    if (pkg.length() == 0) continue;
                    Intent it = pm.getLaunchIntentForPackage(pkg);
                    if (it != null) {
                        startActivity(it);
                        return pkg;
                    }
                }
                // нет в списке — откроем магазин для поиска
                toast("Игра не найдена — открываю Play Маркет");
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW,
                            Uri.parse("market://search?q=car parking multiplayer 2")));
                } catch (Exception ignored) {}
                return "";
            } catch (Exception e) {
                return "";
            }
        }

        @JavascriptInterface
        public void run(final String phasesJson, final String label) {
            DriverService s = DriverService.I;
            if (s == null) { toast("Сначала включи сервис доступности!"); return; }
            boolean ok = s.startManeuver(phasesJson, label);
            if (!ok) toast("Пустой манёвр");
        }

        @JavascriptInterface
        public void replay(String recJson, String label) {
            DriverService s = DriverService.I;
            if (s == null) { toast("Сначала включи сервис доступности!"); return; }
            s.startReplay(recJson, label);
        }

        @JavascriptInterface
        public void stop() {
            DriverService s = DriverService.I;
            if (s != null) s.stopAll(false);
        }

        @JavascriptInterface
        public void recordStart() {
            DriverService s = DriverService.I;
            if (s == null) { toast("Сначала включи сервис доступности!"); return; }
            s.startRecording();
        }

        /** Возвращает JSON потока касаний или null. */
        @JavascriptInterface
        public String recordStop() {
            DriverService s = DriverService.I;
            return s == null ? null : s.stopRecording();
        }

        @JavascriptInterface
        public void setMode(String m) {
            DriverService s = DriverService.I;
            if (s != null) s.setMode(m);
            else prefs().edit().putString("mode", "wheel".equals(m) ? "wheel" : "arrows").apply();
        }

        @JavascriptInterface
        public void setControls(String json) {
            DriverService s = DriverService.I;
            if (s != null) s.setControls(json);
            prefs().edit().putString("controls", json).apply();
        }

        @JavascriptInterface
        public String getControls() {
            DriverService s = DriverService.I;
            return s != null ? s.getControls() : prefs().getString("controls", "{}");
        }

        @JavascriptInterface
        public void setOverlay(boolean vis) {
            DriverService s = DriverService.I;
            if (s != null) s.setOverlayVisible(vis);
            prefs().edit().putBoolean("overlay", vis).apply();
        }

        /** Долговременное хранилище состояний уровней (JSON). */
        @JavascriptInterface
        public void saveLevels(String json) {
            prefs().edit().putString("levels", json).apply();
        }

        @JavascriptInterface
        public String loadLevels() {
            return prefs().getString("levels", "{}");
        }

        @JavascriptInterface
        public void notify(String title, String body) {
            try {
                NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
                if (Build.VERSION.SDK_INT >= 33 &&
                        checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                                != PackageManager.PERMISSION_GRANTED) return;
                Notification.Builder b = Build.VERSION.SDK_INT >= 26
                        ? new Notification.Builder(MainActivity.this, "driver")
                        : new Notification.Builder(MainActivity.this);
                b.setSmallIcon(R.drawable.notif_icon)
                 .setContentTitle(title)
                 .setContentText(body)
                 .setAutoCancel(true);
                nm.notify((int) System.currentTimeMillis() % 100000, b.build());
            } catch (Exception ignored) {}
        }

        @JavascriptInterface
        public void vibrate(long ms) {
            try {
                Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
                if (v == null) return;
                if (Build.VERSION.SDK_INT >= 26) {
                    v.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE));
                } else {
                    v.vibrate(ms);
                }
            } catch (Exception ignored) {}
        }

        @JavascriptInterface
        public void toast(String s) {
            toast(s);
        }

        @JavascriptInterface
        public void keepScreenOn(final boolean on) {
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    if (web != null) web.setKeepScreenOn(on);
                }
            });
        }
    }

    private android.content.SharedPreferences prefs() {
        return getSharedPreferences("cpm2", MODE_PRIVATE);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }
}
