package org.rubus.fenorubus;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.OrientationEventListener;
import android.view.ScaleGestureDetector;
import android.view.Surface;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.activity.ComponentActivity;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.FocusMeteringAction;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.MeteringPoint;
import androidx.camera.core.Preview;
import androidx.camera.core.ZoomState;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

/**
 * Cámara propia de la app: vista previa, zoom 1×/2×/4× (y con dos dedos), enfoque al tocar,
 * disparador y varias fotos seguidas hasta «Listo» (con sus miniaturas abajo).
 *
 * Botones de un estabilizador o control Bluetooth (los que el teléfono recibe como teclas):
 * volumen + / − y las teclas de zoom acercan o alejan; las de cámara, Enter, reproducir o
 * el botón central disparan; la de enfoque enfoca al centro. La última tecla recibida se
 * muestra arriba (para saber qué manda cada botón).
 *
 * Devuelve (RESULT_OK) en el extra «paths» las rutas de las fotos (en la caché de la app).
 */
public class AeonCamera extends ComponentActivity {
    private static final String TAG = "AeonCamera";
    public static final String EXTRA_PATHS = "paths";
    public static final String EXTRA_TITLE = "title";

    private PreviewView preview;
    private ImageCapture capture;
    private Camera camera;
    private final ArrayList<String> paths = new ArrayList<String>();
    private LinearLayout strip;
    private TextView count, keyInfo, title;
    private View focusRing;
    private final TextView[] zoomBtns = new TextView[3];
    private static final float[] ZOOMS = {1f, 2f, 4f};
    private boolean busy = false;
    private OrientationEventListener orientation;

    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    private GradientDrawable round(int color, float radius, int stroke, int strokeColor) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(radius);
        if (stroke > 0) g.setStroke(stroke, strokeColor);
        return g;
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        cleanOld();
        if (state != null && state.getStringArrayList(EXTRA_PATHS) != null) {
            paths.addAll(state.getStringArrayList(EXTRA_PATHS));
        }
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        preview = new PreviewView(this);
        preview.setScaleType(PreviewView.ScaleType.FIT_CENTER);
        root.addView(preview, new FrameLayout.LayoutParams(-1, -1));

        // anillo de enfoque
        focusRing = new View(this);
        focusRing.setBackground(round(Color.TRANSPARENT, dp(36), dp(2), Color.WHITE));
        focusRing.setVisibility(View.INVISIBLE);
        root.addView(focusRing, new FrameLayout.LayoutParams(dp(72), dp(72)));

        // arriba: título y última tecla del control
        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.VERTICAL);
        top.setPadding(dp(16), dp(14), dp(16), dp(8));
        top.setBackgroundColor(0x66000000);
        title = new TextView(this);
        title.setTextColor(Color.WHITE);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        String t = getIntent().getStringExtra(EXTRA_TITLE);
        if (t == null || t.isEmpty()) t = "Cámara";
        // 1.ª línea grande (FOTO GENERAL / FOTO DE DETALLE), 2.ª chica (la parcela o variedad)
        int nl = t.indexOf('\n');
        android.text.SpannableString sp = new android.text.SpannableString(
                nl < 0 ? t.toUpperCase(Locale.ROOT) : t.substring(0, nl).toUpperCase(Locale.ROOT) + t.substring(nl));
        int end = nl < 0 ? sp.length() : nl;
        sp.setSpan(new android.text.style.StyleSpan(android.graphics.Typeface.BOLD), 0, end, 0);
        sp.setSpan(new android.text.style.AbsoluteSizeSpan(22, true), 0, end, 0);
        if (nl >= 0) sp.setSpan(new android.text.style.AbsoluteSizeSpan(15, true), nl, sp.length(), 0);
        title.setText(sp);
        top.addView(title);
        keyInfo = new TextView(this);
        keyInfo.setTextColor(0xCCFFFFFF);
        keyInfo.setTextSize(12);
        keyInfo.setGravity(Gravity.CENTER_HORIZONTAL);
        keyInfo.setText("Botón del control o volumen: toque = foto · mantener = zoom");
        top.addView(keyInfo);
        root.addView(top, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));

        // abajo: zoom, miniaturas y botones
        LinearLayout bottom = new LinearLayout(this);
        bottom.setOrientation(LinearLayout.VERTICAL);
        bottom.setBackgroundColor(0x88000000);
        bottom.setPadding(dp(12), dp(8), dp(12), dp(18));

        LinearLayout zooms = new LinearLayout(this);
        zooms.setGravity(Gravity.CENTER);
        for (int i = 0; i < ZOOMS.length; i++) {
            final float z = ZOOMS[i];
            TextView b = new TextView(this);        // círculo exacto (Button recorta su fondo)
            b.setText(((int) z) + "×");
            b.setTextColor(Color.WHITE);
            b.setTextSize(14);
            b.setGravity(Gravity.CENTER);
            b.setClickable(true);
            b.setBackground(round(0x55FFFFFF, dp(26), 0, 0));
            b.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) { setZoom(z); }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(52), dp(52));
            lp.setMargins(dp(10), dp(4), dp(10), dp(8));
            zooms.addView(b, lp);
            zoomBtns[i] = b;
        }
        bottom.addView(zooms);

        HorizontalScrollView hs = new HorizontalScrollView(this);
        strip = new LinearLayout(this);
        strip.setOrientation(LinearLayout.HORIZONTAL);
        hs.addView(strip);
        bottom.addView(hs, new LinearLayout.LayoutParams(-1, dp(64)));

        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(8), 0, 0);
        count = new TextView(this);
        count.setTextColor(Color.WHITE);
        count.setTextSize(15);
        count.setGravity(Gravity.CENTER);
        row.addView(count, new LinearLayout.LayoutParams(0, -2, 1));

        View shutter = new View(this);
        shutter.setBackground(round(Color.WHITE, dp(38), dp(5), 0xFFA0174A));
        shutter.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { shoot(); }
        });
        row.addView(shutter, new LinearLayout.LayoutParams(dp(76), dp(76)));

        Button done = new Button(this);
        done.setText("Listo");
        done.setTextColor(Color.WHITE);
        done.setAllCaps(false);
        done.setTextSize(16);
        done.setStateListAnimator(null);
        done.setBackground(round(0xFF2E7D4F, dp(24), 0, 0));
        done.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { finishWithPhotos(); }
        });
        LinearLayout.LayoutParams dl = new LinearLayout.LayoutParams(0, dp(48), 1);
        dl.setMargins(dp(22), 0, dp(4), 0);
        row.addView(done, dl);
        bottom.addView(row);
        root.addView(bottom, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        setContentView(root);
        for (String p : paths) addThumb(p);
        updateCount();

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

    private void startCamera() {
        final ListenableFuture<ProcessCameraProvider> f = ProcessCameraProvider.getInstance(this);
        f.addListener(new Runnable() {
            public void run() {
                try {
                    ProcessCameraProvider provider = f.get();
                    Preview pv = new Preview.Builder().build();
                    pv.setSurfaceProvider(preview.getSurfaceProvider());
                    capture = new ImageCapture.Builder()
                            .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
                            .build();
                    provider.unbindAll();
                    camera = provider.bindToLifecycle(AeonCamera.this, CameraSelector.DEFAULT_BACK_CAMERA, pv, capture);
                    markZoom(1f);
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
    }

    // ------------------------------------------------------------------ zoom y enfoque
    private void setZoom(float z) {
        applyZoom(z);
    }

    private void applyZoom(float z) {
        if (camera == null) return;
        ZoomState zs = camera.getCameraInfo().getZoomState().getValue();
        float lo = zs != null ? zs.getMinZoomRatio() : 1f, hi = zs != null ? zs.getMaxZoomRatio() : 4f;
        float v = Math.max(lo, Math.min(hi, z));
        camera.getCameraControl().setZoomRatio(v);
        markZoom(v);
    }

    private void markZoom(float v) {
        for (int i = 0; i < ZOOMS.length; i++) {
            boolean on = Math.abs(ZOOMS[i] - v) < .15f;
            zoomBtns[i].setBackground(round(on ? 0xFFF2C14E : 0x55FFFFFF, dp(26), 0, 0));
            zoomBtns[i].setTextColor(on ? Color.BLACK : Color.WHITE);
        }
        if (camera != null && keyInfo != null) {
            keyInfo.setText(String.format(Locale.US, "Zoom %.1f×", v));
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
        preview.animate().alpha(.3f).setDuration(60).withEndAction(new Runnable() {
            public void run() { preview.animate().alpha(1f).setDuration(120); }
        });
        ImageCapture.OutputFileOptions opts = new ImageCapture.OutputFileOptions.Builder(out).build();
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

    private void addThumb(final String path) {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inSampleSize = 16;
        Bitmap bm = BitmapFactory.decodeFile(path, o);
        final ImageView iv = new ImageView(this);
        iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
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
            }
        });
        strip.addView(iv, lp);
    }

    private void updateCount() {
        int n = paths.size();
        count.setText(n == 0 ? "Sin fotos" : n + (n == 1 ? " foto" : " fotos") + "\n(tocar una la quita)");
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
    // Volumen (lo que envían la mayoría de los estabilizadores y controles Bluetooth):
    //   toque = foto · mantener + = acercar · mantener − = alejar.
    // Otras teclas: cámara, Enter, OK, reproducir/pausa, auricular, botones de mando = foto;
    // siguiente/anterior, ← →, zoom = cambiar entre 1×, 2× y 4×; enfoque = enfocar al centro.
    private boolean held;          // la tecla de volumen se mantuvo (hizo zoom): al soltar, sin foto

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

    /** Siguiente / anterior zoom de los botones 1× 2× 4×. */
    private void zoomPreset(int step) {
        if (camera == null) return;
        ZoomState zs = camera.getCameraInfo().getZoomState().getValue();
        float cur = zs != null ? zs.getZoomRatio() : 1f;
        int i = 0;
        for (int j = 0; j < ZOOMS.length; j++) if (Math.abs(ZOOMS[j] - cur) < Math.abs(ZOOMS[i] - cur)) i = j;
        i = Math.max(0, Math.min(ZOOMS.length - 1, i + step));
        applyZoom(ZOOMS[i]);
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        int k = e.getKeyCode();
        if (k == KeyEvent.KEYCODE_BACK) return super.dispatchKeyEvent(e);
        String name = KeyEvent.keyCodeToString(k).replace("KEYCODE_", "");
        if (e.getAction() == KeyEvent.ACTION_DOWN) {
            if (isVolume(k)) {
                if (e.getRepeatCount() == 0) {
                    held = false;
                } else {                                   // mantenido: zoom continuo
                    held = true;
                    zoomStep(k == KeyEvent.KEYCODE_VOLUME_UP ? 1.06f : 1 / 1.06f);
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
            if (isVolume(k)) {
                if (!held) {                               // toque corto: foto
                    shoot();
                    keyInfo.setText("Botón " + name + " → foto");
                }
                held = false;
                return true;
            }
            if (isShutter(k) || presetStep(k) != 0 || k == KeyEvent.KEYCODE_FOCUS) return true;
        }
        return super.dispatchKeyEvent(e);
    }
}
