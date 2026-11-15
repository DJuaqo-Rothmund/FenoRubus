package org.rubus.fenorubus;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.util.Log;
import android.util.Range;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.OrientationEventListener;
import android.view.ScaleGestureDetector;
import android.view.Surface;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;

import androidx.activity.ComponentActivity;
import androidx.camera.core.AspectRatio;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ExposureState;
import androidx.camera.core.FocusMeteringAction;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.MeteringPoint;
import androidx.camera.core.Preview;
import androidx.camera.core.ZoomState;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.Observer;

import com.google.common.util.concurrent.ListenableFuture;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

/**
 * Cámara propia de la app, al estilo de la cámara del teléfono:
 *
 * - Imagen 9:16 a lo ancho de la pantalla; la foto guardada es exactamente esa imagen (16:9),
 *   y los textos y botones van ENCIMA de la vista previa (no salen en la foto).
 * - Arriba: flash (apagado / automático / encendido), cuadrícula, exposición (±), cámara
 *   delantera o trasera; debajo, qué foto es (FOTO GENERAL / DE DETALLE…) y la parcela.
 * - Zoom en píldoras (0.6 si el teléfono tiene gran angular, 1, 2, 4; la elegida muestra el
 *   zoom real), con dos dedos o con el estabilizador. Tocar la imagen enfoca y mide la luz.
 * - Abajo: miniatura de la última foto (tocarla muestra todas; tocar una la quita), el
 *   disparador y «Listo» (varias fotos seguidas).
 *
 * Botones de un estabilizador o control Bluetooth: volumen = foto;
 * cámara/Enter/reproducir = foto; siguiente/anterior/← → = cambiar de zoom; enfoque = enfocar.
 *
 * Devuelve (RESULT_OK) en el extra «paths» las rutas de las fotos (en la caché de la app).
 */
public class AeonCamera extends ComponentActivity {
    private static final String TAG = "AeonCamera";
    public static final String EXTRA_PATHS = "paths";
    public static final String EXTRA_TITLE = "title";
    private static final int GOLD = 0xFFF2C14E;
    private static final int BERRY = 0xFFC62A6A;
    private static final int GREEN = 0xFF2E7D4F;

    private PreviewView preview;
    private ImageCapture capture;
    private Camera camera;
    private final ArrayList<String> paths = new ArrayList<String>();
    private LinearLayout strip, zooms;
    private HorizontalScrollView stripBox;
    private TextView keyInfo, title, done, thumbBadge, expLabel;
    private ImageView thumb;
    private View focusRing, flashView;
    private GridView grid;
    private Icon flashIcon, gridIcon, expIcon;
    private LinearLayout expBox;
    private SeekBar expBar;
    private final ArrayList<Float> zoomList = new ArrayList<Float>();
    private final ArrayList<TextView> zoomBtns = new ArrayList<TextView>();
    private boolean busy = false, front = false;
    private int flashMode = ImageCapture.FLASH_MODE_OFF;
    private OrientationEventListener orientation;

    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    private static GradientDrawable round(int color, float radius, int stroke, int strokeColor) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(radius);
        if (stroke > 0) g.setStroke(stroke, strokeColor);
        return g;
    }

    private static GradientDrawable fade(boolean down) {
        return new GradientDrawable(down ? GradientDrawable.Orientation.TOP_BOTTOM : GradientDrawable.Orientation.BOTTOM_TOP,
                new int[]{0xB0000000, 0x55000000, 0x00000000});
    }

    // ------------------------------------------------------------------ íconos dibujados
    /** Íconos simples dibujados (sin depender de fuentes de íconos). */
    static class Icon extends View {
        static final int FLASH = 0, GRID = 1, EXPOSURE = 2, SWITCH = 3;
        final int kind;
        int state = 0;          // flash: 0 apagado, 1 auto, 2 encendido · otros: 0/1 activo
        final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);

        Icon(Context c, int kind) {
            super(c);
            this.kind = kind;
            p.setStrokeCap(Paint.Cap.ROUND);
            p.setStrokeJoin(Paint.Join.ROUND);
        }

        @Override
        protected void onDraw(Canvas c) {
            float w = getWidth(), h = getHeight(), s = Math.min(w, h), cx = w / 2, cy = h / 2;
            float u = s / 24f;
            boolean on = kind == FLASH ? state != 0 : state == 1;
            p.setColor(on ? GOLD : Color.WHITE);
            p.setStrokeWidth(1.9f * u);
            p.setStyle(Paint.Style.STROKE);
            if (kind == FLASH) {
                Path b = new Path();
                b.moveTo(cx + 1.5f * u, cy - 9 * u);
                b.lineTo(cx - 5 * u, cy + 1 * u);
                b.lineTo(cx - .5f * u, cy + 1 * u);
                b.lineTo(cx - 1.5f * u, cy + 9 * u);
                b.lineTo(cx + 5 * u, cy - 1.5f * u);
                b.lineTo(cx + .5f * u, cy - 1.5f * u);
                b.close();
                c.drawPath(b, p);
                if (state == 0) c.drawLine(cx - 7 * u, cy - 7 * u, cx + 7 * u, cy + 7 * u, p);
                if (state == 1) {
                    p.setStyle(Paint.Style.FILL);
                    p.setTextSize(7.5f * u);
                    p.setFakeBoldText(true);
                    c.drawText("A", cx + 5 * u, cy + 9 * u, p);
                }
            } else if (kind == GRID) {
                RectF r = new RectF(cx - 8 * u, cy - 8 * u, cx + 8 * u, cy + 8 * u);
                c.drawRoundRect(r, 2 * u, 2 * u, p);
                for (int i = 1; i < 3; i++) {
                    float t = -8 * u + i * 16 * u / 3;
                    c.drawLine(cx + t, cy - 8 * u, cx + t, cy + 8 * u, p);
                    c.drawLine(cx - 8 * u, cy + t, cx + 8 * u, cy + t, p);
                }
            } else if (kind == EXPOSURE) {
                c.drawCircle(cx, cy, 8.5f * u, p);
                c.drawLine(cx - 6 * u, cy + 6 * u, cx + 6 * u, cy - 6 * u, p);
                c.drawLine(cx - 6 * u, cy - 3 * u, cx - 1.5f * u, cy - 3 * u, p);
                c.drawLine(cx - 3.75f * u, cy - 5.25f * u, cx - 3.75f * u, cy - .75f * u, p);
                c.drawLine(cx + 1.5f * u, cy + 3.5f * u, cx + 6 * u, cy + 3.5f * u, p);
            } else {                                  // cambiar cámara: dos flechas en círculo
                RectF r = new RectF(cx - 8 * u, cy - 8 * u, cx + 8 * u, cy + 8 * u);
                c.drawArc(r, 200, 140, false, p);
                c.drawArc(r, 20, 140, false, p);
                c.drawLine(cx + 7.5f * u, cy - 3 * u, cx + 8 * u, cy + 1.5f * u, p);
                c.drawLine(cx + 8 * u, cy + 1.5f * u, cx + 4 * u, cy - .5f * u, p);
                c.drawLine(cx - 7.5f * u, cy + 3 * u, cx - 8 * u, cy - 1.5f * u, p);
                c.drawLine(cx - 8 * u, cy - 1.5f * u, cx - 4 * u, cy + .5f * u, p);
            }
        }
    }

    /** Cuadrícula de tercios dentro del área real de la foto (9:16 centrada). */
    static class GridView extends View {
        final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        boolean show = true;

        GridView(Context c) {
            super(c);
            p.setColor(0x80FFFFFF);
            p.setStrokeWidth(Math.max(1f, c.getResources().getDisplayMetrics().density * .8f));
        }

        RectF area() {
            float w = getWidth(), h = getHeight();
            float ph = Math.min(h, w * 16f / 9f), pw = ph * 9f / 16f;
            return new RectF((w - pw) / 2, (h - ph) / 2, (w + pw) / 2, (h + ph) / 2);
        }

        @Override
        protected void onDraw(Canvas c) {
            if (!show) return;
            RectF a = area();
            for (int i = 1; i < 3; i++) {
                float x = a.left + a.width() * i / 3, y = a.top + a.height() * i / 3;
                c.drawLine(x, a.top, x, a.bottom, p);
                c.drawLine(a.left, y, a.right, y, p);
            }
        }
    }

    private Icon topIcon(int kind, View.OnClickListener l) {
        Icon i = new Icon(this, kind);
        i.setClickable(true);
        i.setOnClickListener(l);
        return i;
    }

    // ------------------------------------------------------------------ pantalla
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        cleanOld();
        if (state != null && state.getStringArrayList(EXTRA_PATHS) != null) {
            paths.addAll(state.getStringArrayList(EXTRA_PATHS));
        }
        if (state != null) front = state.getBoolean("front", false);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        // Vista previa 9:16 a todo el ancho (igual que la foto que se guarda).
        preview = new PreviewView(this);
        preview.setScaleType(PreviewView.ScaleType.FIT_CENTER);
        preview.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);
        root.addView(preview, new FrameLayout.LayoutParams(-1, -1));
        grid = new GridView(this);
        root.addView(grid, new FrameLayout.LayoutParams(-1, -1));
        flashView = new View(this);                 // destello blanco al disparar
        flashView.setBackgroundColor(Color.WHITE);
        flashView.setAlpha(0f);
        root.addView(flashView, new FrameLayout.LayoutParams(-1, -1));

        focusRing = new View(this);
        focusRing.setBackground(round(Color.TRANSPARENT, dp(36), dp(2), GOLD));
        focusRing.setVisibility(View.INVISIBLE);
        root.addView(focusRing, new FrameLayout.LayoutParams(dp(72), dp(72)));

        // ---- arriba: íconos y título (encima de la imagen, con degradado)
        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.VERTICAL);
        top.setPadding(dp(14), dp(10), dp(14), dp(22));
        top.setBackground(fade(true));
        LinearLayout icons = new LinearLayout(this);
        icons.setGravity(Gravity.CENTER_VERTICAL);
        flashIcon = topIcon(Icon.FLASH, new View.OnClickListener() {
            public void onClick(View v) { cycleFlash(); }
        });
        gridIcon = topIcon(Icon.GRID, new View.OnClickListener() {
            public void onClick(View v) { toggleGrid(); }
        });
        expIcon = topIcon(Icon.EXPOSURE, new View.OnClickListener() {
            public void onClick(View v) { toggleExposure(); }
        });
        Icon sw = topIcon(Icon.SWITCH, new View.OnClickListener() {
            public void onClick(View v) { front = !front; startCamera(); }
        });
        gridIcon.state = 1;
        Icon[] row = {flashIcon, gridIcon, expIcon, sw};
        for (int i = 0; i < row.length; i++) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(44), dp(44));
            if (i == row.length - 1) {
                icons.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1));
            } else {
                lp.setMargins(0, 0, dp(14), 0);
            }
            icons.addView(row[i], lp);
        }
        top.addView(icons);
        title = new TextView(this);
        title.setTextColor(Color.WHITE);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        title.setShadowLayer(dp(3), 0, dp(1), 0xCC000000);
        String t = getIntent().getStringExtra(EXTRA_TITLE);
        if (t == null || t.isEmpty()) t = "Cámara";
        // 1.ª línea grande (FOTO GENERAL / FOTO DE DETALLE), 2.ª chica (la parcela o variedad)
        int nl = t.indexOf('\n');
        android.text.SpannableString sp = new android.text.SpannableString(
                nl < 0 ? t.toUpperCase(Locale.ROOT) : t.substring(0, nl).toUpperCase(Locale.ROOT) + t.substring(nl));
        int end = nl < 0 ? sp.length() : nl;
        sp.setSpan(new android.text.style.StyleSpan(android.graphics.Typeface.BOLD), 0, end, 0);
        sp.setSpan(new android.text.style.AbsoluteSizeSpan(21, true), 0, end, 0);
        if (nl >= 0) sp.setSpan(new android.text.style.AbsoluteSizeSpan(15, true), nl, sp.length(), 0);
        title.setText(sp);
        LinearLayout.LayoutParams tl = new LinearLayout.LayoutParams(-1, -2);
        tl.setMargins(0, dp(4), 0, 0);
        top.addView(title, tl);
        keyInfo = new TextView(this);
        keyInfo.setTextColor(0xDDFFFFFF);
        keyInfo.setTextSize(12);
        keyInfo.setGravity(Gravity.CENTER_HORIZONTAL);
        keyInfo.setShadowLayer(dp(3), 0, dp(1), 0xCC000000);
        keyInfo.setText("Botón del control o de volumen: foto");
        top.addView(keyInfo);
        root.addView(top, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));

        // ---- abajo: exposición, zoom, miniaturas, disparador y Listo (encima de la imagen)
        LinearLayout bottom = new LinearLayout(this);
        bottom.setOrientation(LinearLayout.VERTICAL);
        bottom.setBackground(fade(false));
        bottom.setPadding(dp(14), dp(30), dp(14), dp(20));

        expBox = new LinearLayout(this);
        expBox.setGravity(Gravity.CENTER_VERTICAL);
        expBox.setVisibility(View.GONE);
        expLabel = new TextView(this);
        expLabel.setTextColor(Color.WHITE);
        expLabel.setTextSize(13);
        expLabel.setGravity(Gravity.CENTER);
        expBar = new SeekBar(this);
        expBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar s, int v, boolean user) { if (user) setExposure(v); }
            public void onStartTrackingTouch(SeekBar s) {}
            public void onStopTrackingTouch(SeekBar s) {}
        });
        expBox.addView(expLabel, new LinearLayout.LayoutParams(dp(56), -2));
        expBox.addView(expBar, new LinearLayout.LayoutParams(0, -2, 1));
        bottom.addView(expBox, new LinearLayout.LayoutParams(-1, dp(40)));

        LinearLayout zoomRow = new LinearLayout(this);
        zoomRow.setGravity(Gravity.CENTER);
        zooms = new LinearLayout(this);
        zooms.setGravity(Gravity.CENTER);
        zooms.setPadding(dp(6), dp(4), dp(6), dp(4));
        zooms.setBackground(round(0x66000000, dp(26), 0, 0));
        zoomRow.addView(zooms);
        bottom.addView(zoomRow);

        stripBox = new HorizontalScrollView(this);
        strip = new LinearLayout(this);
        strip.setOrientation(LinearLayout.HORIZONTAL);
        stripBox.addView(strip);
        stripBox.setVisibility(View.GONE);
        LinearLayout.LayoutParams sl = new LinearLayout.LayoutParams(-1, dp(64));
        sl.setMargins(0, dp(10), 0, 0);
        bottom.addView(stripBox, sl);

        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(0, dp(16), 0, 0);
        FrameLayout thumbBox = new FrameLayout(this);
        thumb = new ImageView(this);
        thumb.setScaleType(ImageView.ScaleType.CENTER_CROP);
        thumb.setBackground(round(0x44FFFFFF, dp(10), dp(2), 0xCCFFFFFF));
        thumb.setClipToOutline(true);
        thumb.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                if (paths.isEmpty()) return;
                boolean show = stripBox.getVisibility() != View.VISIBLE;
                stripBox.setVisibility(show ? View.VISIBLE : View.GONE);
                keyInfo.setText(show ? "Toque una miniatura para quitarla" : "");
            }
        });
        thumbBox.addView(thumb, new FrameLayout.LayoutParams(dp(54), dp(54), Gravity.CENTER));
        thumbBadge = new TextView(this);
        thumbBadge.setTextColor(Color.WHITE);
        thumbBadge.setTextSize(11);
        thumbBadge.setGravity(Gravity.CENTER);
        thumbBadge.setBackground(round(BERRY, dp(10), 0, 0));
        FrameLayout.LayoutParams bl = new FrameLayout.LayoutParams(dp(22), dp(20), Gravity.TOP | Gravity.RIGHT);
        thumbBox.addView(thumbBadge, bl);
        LinearLayout.LayoutParams tbl = new LinearLayout.LayoutParams(0, dp(64), 1);
        bar.addView(thumbBox, tbl);

        FrameLayout shutterBox = new FrameLayout(this);
        View ring = new View(this);
        ring.setBackground(round(Color.TRANSPARENT, dp(42), dp(4), Color.WHITE));
        shutterBox.addView(ring, new FrameLayout.LayoutParams(dp(84), dp(84), Gravity.CENTER));
        final View shutter = new View(this);
        shutter.setBackground(round(Color.WHITE, dp(34), 0, 0));
        shutter.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                shutter.animate().scaleX(.86f).scaleY(.86f).setDuration(70).withEndAction(new Runnable() {
                    public void run() { shutter.animate().scaleX(1f).scaleY(1f).setDuration(110); }
                });
                shoot();
            }
        });
        shutterBox.addView(shutter, new FrameLayout.LayoutParams(dp(68), dp(68), Gravity.CENTER));
        bar.addView(shutterBox, new LinearLayout.LayoutParams(dp(92), dp(92)));

        FrameLayout doneBox = new FrameLayout(this);
        done = new TextView(this);
        done.setTextColor(Color.WHITE);
        done.setTextSize(16);
        done.setGravity(Gravity.CENTER);
        done.setTypeface(null, android.graphics.Typeface.BOLD);
        done.setBackground(round(GREEN, dp(24), 0, 0));
        done.setClickable(true);
        done.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { finishWithPhotos(); }
        });
        doneBox.addView(done, new FrameLayout.LayoutParams(dp(112), dp(48), Gravity.CENTER));
        bar.addView(doneBox, new LinearLayout.LayoutParams(0, dp(64), 1));
        bottom.addView(bar);
        root.addView(bottom, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        setContentView(root);
        for (String p : paths) addThumb(p);
        updateCount();
        buildZooms(1f);

        final ScaleGestureDetector pinch = new ScaleGestureDetector(this,
                new ScaleGestureDetector.SimpleOnScaleGestureListener() {
                    @Override
                    public boolean onScale(ScaleGestureDetector d) {
                        if (camera == null) return false;
                        ZoomState zs = camera.getCameraInfo().getZoomState().getValue();
                        if (zs != null) applyZoom(zs.getZoomRatio() * d.getScaleFactor());
                        return true;
                    }
                });
        preview.setOnTouchListener(new View.OnTouchListener() {
            public boolean onTouch(View v, MotionEvent e) {
                pinch.onTouchEvent(e);
                if (e.getActionMasked() == MotionEvent.ACTION_UP && !pinch.isInProgress() && e.getPointerCount() == 1) {
                    focusAt(e.getX(), e.getY());
                }
                return true;
            }
        });

        orientation = new OrientationEventListener(this) {
            @Override
            public void onOrientationChanged(int deg) {
                if (deg == ORIENTATION_UNKNOWN || capture == null) return;
                int rot = deg >= 45 && deg < 135 ? Surface.ROTATION_270
                        : deg >= 135 && deg < 225 ? Surface.ROTATION_180
                        : deg >= 225 && deg < 315 ? Surface.ROTATION_90 : Surface.ROTATION_0;
                capture.setTargetRotation(rot);
            }
        };
        startCamera();
    }

    /** Fotos de la caché de días anteriores (la app ya las guardó en su carpeta). */
    private void cleanOld() {
        File[] old = new File(getCacheDir(), "aeoncam").listFiles();
        if (old == null) return;
        long limit = System.currentTimeMillis() - 2L * 24 * 3600 * 1000;
        for (File f : old) if (f.lastModified() < limit) f.delete();
    }

    @SuppressWarnings("deprecation")
    private void startCamera() {
        final ListenableFuture<ProcessCameraProvider> f = ProcessCameraProvider.getInstance(this);
        f.addListener(new Runnable() {
            public void run() {
                try {
                    ProcessCameraProvider provider = f.get();
                    // 16:9 en la vista previa y en la foto: lo que se ve es lo que se guarda.
                    Preview pv = new Preview.Builder().setTargetAspectRatio(AspectRatio.RATIO_16_9).build();
                    pv.setSurfaceProvider(preview.getSurfaceProvider());
                    capture = new ImageCapture.Builder()
                            .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
                            .setTargetAspectRatio(AspectRatio.RATIO_16_9)
                            .setFlashMode(flashMode)
                            .build();
                    provider.unbindAll();
                    CameraSelector sel = front ? CameraSelector.DEFAULT_FRONT_CAMERA : CameraSelector.DEFAULT_BACK_CAMERA;
                    camera = provider.bindToLifecycle(AeonCamera.this, sel, pv, capture);
                    ZoomState zs = camera.getCameraInfo().getZoomState().getValue();
                    buildZooms(zs != null ? zs.getMinZoomRatio() : 1f);
                    // El zoom mínimo (gran angular 0.6×) a veces llega un momento después.
                    camera.getCameraInfo().getZoomState().observe(AeonCamera.this, new Observer<ZoomState>() {
                        public void onChanged(ZoomState z) {
                            if (z == null) return;
                            boolean wide = z.getMinZoomRatio() < .95f;
                            if (wide != (!zoomList.isEmpty() && zoomList.get(0) < .95f)) buildZooms(z.getMinZoomRatio());
                            markZoom(z.getZoomRatio());
                        }
                    });
                    setupExposure();
                } catch (Exception e) {
                    Log.e(TAG, "camera", e);
                    keyInfo.setText("No se pudo abrir la cámara: " + e.getMessage());
                }
            }
        }, ContextCompat.getMainExecutor(this));
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (orientation != null && orientation.canDetectOrientation()) orientation.enable();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (orientation != null) orientation.disable();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        out.putStringArrayList(EXTRA_PATHS, paths);
        out.putBoolean("front", front);
    }

    // ------------------------------------------------------------------ flash, cuadrícula, exposición
    private void cycleFlash() {
        flashMode = flashMode == ImageCapture.FLASH_MODE_OFF ? ImageCapture.FLASH_MODE_AUTO
                : flashMode == ImageCapture.FLASH_MODE_AUTO ? ImageCapture.FLASH_MODE_ON : ImageCapture.FLASH_MODE_OFF;
        flashIcon.state = flashMode == ImageCapture.FLASH_MODE_OFF ? 0 : flashMode == ImageCapture.FLASH_MODE_AUTO ? 1 : 2;
        flashIcon.invalidate();
        if (capture != null) capture.setFlashMode(flashMode);
        keyInfo.setText(flashIcon.state == 0 ? "Flash apagado" : flashIcon.state == 1 ? "Flash automático" : "Flash encendido");
    }

    private void toggleGrid() {
        grid.show = !grid.show;
        gridIcon.state = grid.show ? 1 : 0;
        gridIcon.invalidate();
        grid.invalidate();
    }

    private void setupExposure() {
        if (camera == null) return;
        ExposureState es = camera.getCameraInfo().getExposureState();
        if (!es.isExposureCompensationSupported()) {
            expIcon.setAlpha(.35f);
            return;
        }
        Range<Integer> r = es.getExposureCompensationRange();
        expBar.setMax(r.getUpper() - r.getLower());
        expBar.setProgress(es.getExposureCompensationIndex() - r.getLower());
        showExposure(es.getExposureCompensationIndex());
    }

    private void toggleExposure() {
        if (camera == null || !camera.getCameraInfo().getExposureState().isExposureCompensationSupported()) {
            keyInfo.setText("Este teléfono no permite ajustar la exposición");
            return;
        }
        boolean show = expBox.getVisibility() != View.VISIBLE;
        expBox.setVisibility(show ? View.VISIBLE : View.GONE);
        expIcon.state = show ? 1 : 0;
        expIcon.invalidate();
    }

    private void setExposure(int progress) {
        if (camera == null) return;
        ExposureState es = camera.getCameraInfo().getExposureState();
        int idx = es.getExposureCompensationRange().getLower() + progress;
        camera.getCameraControl().setExposureCompensationIndex(idx);
        showExposure(idx);
    }

    private void showExposure(int idx) {
        if (camera == null) return;
        float ev = idx * camera.getCameraInfo().getExposureState().getExposureCompensationStep().floatValue();
        expLabel.setText(String.format(Locale.US, "%+.1f", ev));
    }

    // ------------------------------------------------------------------ zoom y enfoque
    /** Píldoras de zoom: 0.6 (si hay gran angular), 1, 2 y 4. */
    private void buildZooms(float minZoom) {
        zooms.removeAllViews();
        zoomList.clear();
        zoomBtns.clear();
        if (minZoom < .95f) zoomList.add(Math.max(minZoom, .6f));
        zoomList.add(1f);
        zoomList.add(2f);
        zoomList.add(4f);
        for (int i = 0; i < zoomList.size(); i++) {
            final float z = zoomList.get(i);
            TextView b = new TextView(this);
            b.setTextColor(Color.WHITE);
            b.setTextSize(13);
            b.setGravity(Gravity.CENTER);
            b.setClickable(true);
            b.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) { applyZoom(z); }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(46), dp(40));
            lp.setMargins(dp(2), 0, dp(2), 0);
            zooms.addView(b, lp);
            zoomBtns.add(b);
        }
        markZoom(1f);
    }

    private static String fmt(float z) {
        return Math.abs(z - Math.round(z)) < .05f ? String.valueOf(Math.round(z)) : String.format(Locale.US, "%.1f", z);
    }

    private void applyZoom(float z) {
        if (camera == null) return;
        ZoomState zs = camera.getCameraInfo().getZoomState().getValue();
        float lo = zs != null ? zs.getMinZoomRatio() : 1f, hi = zs != null ? zs.getMaxZoomRatio() : 4f;
        float v = Math.max(lo, Math.min(hi, z));
        camera.getCameraControl().setZoomRatio(v);
        markZoom(v);
    }

    /** La píldora más cercana al zoom actual se marca en dorado y muestra el zoom real (1.2×). */
    private void markZoom(float v) {
        int near = 0;
        for (int i = 0; i < zoomList.size(); i++) {
            if (zoomList.get(i) <= v + .05f) near = i;
        }
        for (int i = 0; i < zoomBtns.size(); i++) {
            TextView b = zoomBtns.get(i);
            boolean on = i == near;
            b.setText(on ? fmt(v) + "×" : fmt(zoomList.get(i)));
            b.setTextColor(on ? GOLD : Color.WHITE);
            b.setTypeface(null, on ? android.graphics.Typeface.BOLD : android.graphics.Typeface.NORMAL);
            b.setBackground(on ? round(0x33000000, dp(20), dp(1), 0x66F2C14E) : null);
        }
    }

    private void zoomStep(float factor) {
        if (camera == null) return;
        ZoomState zs = camera.getCameraInfo().getZoomState().getValue();
        applyZoom((zs != null ? zs.getZoomRatio() : 1f) * factor);
    }

    private void focusAt(float x, float y) {
        if (camera == null) return;
        MeteringPoint p = preview.getMeteringPointFactory().createPoint(x, y);
        FocusMeteringAction a = new FocusMeteringAction.Builder(p,
                FocusMeteringAction.FLAG_AF | FocusMeteringAction.FLAG_AE)
                .setAutoCancelDuration(4, TimeUnit.SECONDS).build();
        camera.getCameraControl().startFocusAndMetering(a);
        focusRing.setX(x - dp(36));
        focusRing.setY(y - dp(36));
        focusRing.setVisibility(View.VISIBLE);
        focusRing.setAlpha(1f);
        focusRing.setScaleX(1.3f);
        focusRing.setScaleY(1.3f);
        focusRing.animate().scaleX(1f).scaleY(1f).setDuration(200).withEndAction(new Runnable() {
            public void run() { focusRing.animate().alpha(0f).setStartDelay(900).setDuration(300); }
        });
    }

    // ------------------------------------------------------------------ fotos
    private void shoot() {
        if (capture == null || busy) return;
        busy = true;
        File dir = new File(getCacheDir(), "aeoncam");
        dir.mkdirs();
        String name = "cam_" + new SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(new Date()) + ".jpg";
        final File out = new File(dir, name);
        flashView.setAlpha(.7f);
        flashView.animate().alpha(0f).setDuration(220);
        ImageCapture.Metadata md = new ImageCapture.Metadata();
        md.setReversedHorizontal(front);
        ImageCapture.OutputFileOptions opts = new ImageCapture.OutputFileOptions.Builder(out).setMetadata(md).build();
        capture.takePicture(opts, ContextCompat.getMainExecutor(this), new ImageCapture.OnImageSavedCallback() {
            public void onImageSaved(ImageCapture.OutputFileResults r) {
                busy = false;
                paths.add(out.getAbsolutePath());
                addThumb(out.getAbsolutePath());
                updateCount();
            }

            public void onError(ImageCaptureException e) {
                busy = false;
                Log.e(TAG, "capture", e);
                keyInfo.setText("No se pudo sacar la foto: " + e.getMessage());
            }
        });
    }

    private Bitmap small(String path) {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inSampleSize = 16;
        return BitmapFactory.decodeFile(path, o);
    }

    private void addThumb(final String path) {
        final ImageView iv = new ImageView(this);
        iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
        Bitmap bm = small(path);
        if (bm != null) iv.setImageBitmap(bm);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(58), dp(58));
        lp.setMargins(0, 0, dp(6), 0);
        // tocar una miniatura la quita (por si salió movida)
        iv.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                paths.remove(path);
                new File(path).delete();
                strip.removeView(iv);
                updateCount();
                keyInfo.setText("Foto quitada");
                if (paths.isEmpty()) stripBox.setVisibility(View.GONE);
            }
        });
        strip.addView(iv, lp);
    }

    private void updateCount() {
        int n = paths.size();
        done.setText(n == 0 ? "Listo" : "Listo (" + n + ")");
        thumbBadge.setText(String.valueOf(n));
        thumbBadge.setVisibility(n == 0 ? View.INVISIBLE : View.VISIBLE);
        if (n == 0) {
            thumb.setImageDrawable(null);
        } else {
            Bitmap bm = small(paths.get(n - 1));
            if (bm != null) thumb.setImageBitmap(bm);
        }
    }

    private void finishWithPhotos() {
        Intent data = new Intent();
        data.putExtra(EXTRA_PATHS, paths.toArray(new String[0]));
        setResult(paths.isEmpty() ? Activity.RESULT_CANCELED : Activity.RESULT_OK, data);
        finish();
    }

    @Override
    public void onBackPressed() {
        finishWithPhotos();          // atrás = Listo (no se pierden las fotos sacadas)
    }

    // ------------------------------------------------------------------ estabilizador / control
    // Volumen (lo que envían la mayoría de los estabilizadores y controles Bluetooth): foto.
    // Otras teclas: cámara, Enter, OK, reproducir/pausa, auricular, botones de mando = foto;
    // siguiente/anterior, ← →, zoom = cambiar de píldora de zoom; enfoque = enfocar al centro.

    private static boolean isVolume(int k) {
        return k == KeyEvent.KEYCODE_VOLUME_UP || k == KeyEvent.KEYCODE_VOLUME_DOWN;
    }

    private static boolean isShutter(int k) {
        switch (k) {
            case KeyEvent.KEYCODE_CAMERA: case KeyEvent.KEYCODE_ENTER: case KeyEvent.KEYCODE_NUMPAD_ENTER:
            case KeyEvent.KEYCODE_DPAD_CENTER: case KeyEvent.KEYCODE_SPACE:
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE: case KeyEvent.KEYCODE_MEDIA_PLAY:
            case KeyEvent.KEYCODE_MEDIA_PAUSE: case KeyEvent.KEYCODE_MEDIA_STOP:
            case KeyEvent.KEYCODE_HEADSETHOOK: case KeyEvent.KEYCODE_MEDIA_RECORD:
            case KeyEvent.KEYCODE_BUTTON_A: case KeyEvent.KEYCODE_BUTTON_B:
            case KeyEvent.KEYCODE_BUTTON_X: case KeyEvent.KEYCODE_BUTTON_Y:
            case KeyEvent.KEYCODE_BUTTON_1: case KeyEvent.KEYCODE_BUTTON_2:
            case KeyEvent.KEYCODE_BUTTON_R1: case KeyEvent.KEYCODE_BUTTON_L1:
                return true;
            default:
                return false;
        }
    }

    private static int presetStep(int k) {
        switch (k) {
            case KeyEvent.KEYCODE_MEDIA_NEXT: case KeyEvent.KEYCODE_DPAD_RIGHT:
            case KeyEvent.KEYCODE_ZOOM_IN: case KeyEvent.KEYCODE_DPAD_UP: case KeyEvent.KEYCODE_PAGE_UP:
            case KeyEvent.KEYCODE_MEDIA_FAST_FORWARD:
                return 1;
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS: case KeyEvent.KEYCODE_DPAD_LEFT:
            case KeyEvent.KEYCODE_ZOOM_OUT: case KeyEvent.KEYCODE_DPAD_DOWN: case KeyEvent.KEYCODE_PAGE_DOWN:
            case KeyEvent.KEYCODE_MEDIA_REWIND:
                return -1;
            default:
                return 0;
        }
    }

    /** Siguiente / anterior píldora de zoom. */
    private void zoomPreset(int step) {
        if (camera == null || zoomList.isEmpty()) return;
        ZoomState zs = camera.getCameraInfo().getZoomState().getValue();
        float cur = zs != null ? zs.getZoomRatio() : 1f;
        int i = 0;
        for (int j = 0; j < zoomList.size(); j++) {
            if (Math.abs(zoomList.get(j) - cur) < Math.abs(zoomList.get(i) - cur)) i = j;
        }
        i = Math.max(0, Math.min(zoomList.size() - 1, i + step));
        applyZoom(zoomList.get(i));
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        int k = e.getKeyCode();
        if (k == KeyEvent.KEYCODE_BACK) return super.dispatchKeyEvent(e);
        String name = KeyEvent.keyCodeToString(k).replace("KEYCODE_", "");
        if (e.getAction() == KeyEvent.ACTION_DOWN) {
            if (isVolume(k)) {                             // volumen: foto al presionar (sin repetir)
                if (e.getRepeatCount() == 0) {
                    shoot();
                    keyInfo.setText("Botón " + name + " → foto");
                }
                return true;
            }
            String what = null;
            int step = presetStep(k);
            if (isShutter(k)) {
                if (e.getRepeatCount() == 0) shoot();
                what = "foto";
            } else if (step != 0) {
                if (e.getRepeatCount() == 0) zoomPreset(step);
                what = step > 0 ? "más zoom" : "menos zoom";
            } else if (k == KeyEvent.KEYCODE_FOCUS) {
                focusAt(preview.getWidth() / 2f, preview.getHeight() / 2f);
                what = "enfocar";
            }
            keyInfo.setText("Botón " + name + (what != null ? " → " + what : " (sin uso)"));
            if (what != null) return true;
        } else if (e.getAction() == KeyEvent.ACTION_UP) {
            if (isVolume(k)) return true;
            if (isShutter(k) || presetStep(k) != 0 || k == KeyEvent.KEYCODE_FOCUS) return true;
        }
        return super.dispatchKeyEvent(e);
    }
}
