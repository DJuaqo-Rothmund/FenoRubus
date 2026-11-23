package org.rubus.fenorubus;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Rect;
import android.media.ExifInterface;
import android.util.Log;

import java.nio.FloatBuffer;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

/**
 * Aeon IA en el teléfono: el detector de estructuras (YOLOv8 exportado a ONNX, el mismo archivo
 * que usa la web) con ONNX Runtime. Python (aeon_ai.py) llama a detect() desde un hilo de fondo
 * y recibe las cajas en texto: «clase,puntaje,x0,y0,x1,y1;…» (x, y de 0 a 1 sobre la foto derecha).
 *
 * Entrada: foto RGB 0–1 en un cuadrado imgsz×imgsz (letterbox, relleno gris 114).
 * Salida: [1, 4 + nc, N] → (cx, cy, w, h en píxeles del cuadrado, luego un puntaje por clase).
 */
public class AeonDetector {
    private static final String TAG = "AeonDetector";
    private static OrtEnvironment env;
    private static OrtSession session;
    private static String sessionPath = "";

    private static synchronized OrtSession load(String modelPath) throws Exception {
        if (session != null && sessionPath.equals(modelPath)) return session;
        if (env == null) env = OrtEnvironment.getEnvironment();
        if (session != null) {
            try { session.close(); } catch (Exception ignored) { }
            session = null;
        }
        OrtSession.SessionOptions opts = new OrtSession.SessionOptions();
        opts.setIntraOpNumThreads(Math.max(1, Math.min(4, Runtime.getRuntime().availableProcessors())));
        session = env.createSession(modelPath, opts);
        sessionPath = modelPath;
        return session;
    }

    /** Foto derecha (orientación EXIF) y achicada a no más de 2×side por lado. */
    private static Bitmap readUpright(String path, int side) throws Exception {
        BitmapFactory.Options b = new BitmapFactory.Options();
        b.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(path, b);
        int sample = 1;
        while (Math.max(b.outWidth, b.outHeight) / (sample * 2) >= side * 2) sample *= 2;
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inSampleSize = sample;
        o.inPreferredConfig = Bitmap.Config.ARGB_8888;
        Bitmap bmp = BitmapFactory.decodeFile(path, o);
        if (bmp == null) throw new Exception("no se pudo leer la foto");
        int rot = 0;
        try {
            int or = new ExifInterface(path).getAttributeInt(ExifInterface.TAG_ORIENTATION,
                    ExifInterface.ORIENTATION_NORMAL);
            if (or == ExifInterface.ORIENTATION_ROTATE_90) rot = 90;
            else if (or == ExifInterface.ORIENTATION_ROTATE_180) rot = 180;
            else if (or == ExifInterface.ORIENTATION_ROTATE_270) rot = 270;
        } catch (Exception ignored) { }
        if (rot != 0) {
            Matrix m = new Matrix();
            m.postRotate(rot);
            Bitmap r = Bitmap.createBitmap(bmp, 0, 0, bmp.getWidth(), bmp.getHeight(), m, true);
            if (r != bmp) bmp.recycle();
            bmp = r;
        }
        return bmp;
    }

    private static float iou(float[] a, float[] b) {
        float ix = Math.max(0f, Math.min(a[4], b[4]) - Math.max(a[2], b[2]));
        float iy = Math.max(0f, Math.min(a[5], b[5]) - Math.max(a[3], b[3]));
        float inter = ix * iy;
        float u = (a[4] - a[2]) * (a[5] - a[3]) + (b[4] - b[2]) * (b[5] - b[3]) - inter;
        return u > 0 ? inter / u : 0f;
    }

    // ---- Llamada sin bloquear: Python llama start() desde la interfaz y luego poll() cada
    // fracción de segundo (pyjnius no suelta Python mientras Java trabaja: si detect() se
    // llamara directo, la app quedaría congelada mientras analiza la foto).
    private static volatile boolean busy = false;
    private static volatile String result = null;
    private static volatile String stage = "";

    public static synchronized boolean start(final String modelPath, final String imagePath, final int imgsz,
                                             final float conf, final float iouThr, final int maxBoxes) {
        if (busy) return false;
        busy = true;
        result = null;
        stage = "inicio";
        new Thread(new Runnable() {
            @Override
            public void run() {
                String r;
                try {
                    r = detect(modelPath, imagePath, imgsz, conf, iouThr, maxBoxes);
                } catch (Throwable e) {
                    r = "ERROR:" + e;
                }
                result = r;
                busy = false;
            }
        }, "AeonDetector").start();
        return true;
    }

    /** null mientras analiza; después, el resultado de detect(). */
    public static String poll() {
        return busy ? null : result;
    }

    /** Etapa en curso (para avisar si demora): «modelo», «foto», «analizando», «cajas». */
    public static String stage() {
        return stage;
    }

    public static String detect(String modelPath, String imagePath, int imgsz, float conf, float iouThr,
                                int maxBoxes) {
        try {
            long t0 = System.currentTimeMillis();
            stage = "modelo";
            OrtSession s = load(modelPath);
            long t1 = System.currentTimeMillis();
            stage = "foto";
            Bitmap src = readUpright(imagePath, imgsz);
            int W = src.getWidth(), H = src.getHeight();
            float k = Math.min((float) imgsz / W, (float) imgsz / H);
            int w = Math.round(W * k), h = Math.round(H * k);
            int px = (imgsz - w) / 2, py = (imgsz - h) / 2;
            Bitmap box = Bitmap.createBitmap(imgsz, imgsz, Bitmap.Config.ARGB_8888);
            Canvas c = new Canvas(box);
            c.drawColor(Color.rgb(114, 114, 114));
            Paint p = new Paint(Paint.FILTER_BITMAP_FLAG);
            c.drawBitmap(src, new Rect(0, 0, W, H), new Rect(px, py, px + w, py + h), p);
            src.recycle();
            int n = imgsz * imgsz;
            int[] px32 = new int[n];
            box.getPixels(px32, 0, imgsz, 0, 0, imgsz, imgsz);
            box.recycle();
            FloatBuffer fb = FloatBuffer.allocate(3 * n);
            float[] chw = fb.array();
            for (int i = 0; i < n; i++) {
                int v = px32[i];
                chw[i] = ((v >> 16) & 0xFF) / 255f;
                chw[n + i] = ((v >> 8) & 0xFF) / 255f;
                chw[2 * n + i] = (v & 0xFF) / 255f;
            }
            String input = s.getInputNames().iterator().next();
            Map<String, OnnxTensor> feeds = new HashMap<>();
            OnnxTensor t = OnnxTensor.createTensor(env, fb, new long[]{1, 3, imgsz, imgsz});
            feeds.put(input, t);
            List<float[]> cand = new ArrayList<>();
            stage = "analizando";
            long t2 = System.currentTimeMillis();
            try (OrtSession.Result res = s.run(feeds)) {
                float[][][] out = (float[][][]) res.get(0).getValue();
                float[][] d = out[0];             // [4 + nc][N]
                int rows = d.length, N = d[0].length, nc = rows - 4;
                for (int j = 0; j < N; j++) {
                    int ci = -1;
                    float best = -1f;
                    for (int ch = 0; ch < nc; ch++) {
                        if (d[4 + ch][j] > best) { best = d[4 + ch][j]; ci = ch; }
                    }
                    if (best < conf) continue;
                    float cx = d[0][j], cy = d[1][j], bw = d[2][j], bh = d[3][j];
                    float x0 = Math.max(0f, (cx - bw / 2 - px) / k), y0 = Math.max(0f, (cy - bh / 2 - py) / k);
                    float x1 = Math.min(W, (cx + bw / 2 - px) / k), y1 = Math.min(H, (cy + bh / 2 - py) / k);
                    if (x1 - x0 < 2 || y1 - y0 < 2) continue;
                    cand.add(new float[]{ci, best, x0, y0, x1, y1});
                }
            } finally {
                t.close();
            }
            long t3 = System.currentTimeMillis();
            stage = "cajas";
            Collections.sort(cand, new Comparator<float[]>() {
                @Override
                public int compare(float[] a, float[] b) { return Float.compare(b[1], a[1]); }
            });
            List<float[]> keep = new ArrayList<>();
            for (float[] b : cand) {
                boolean dup = false;
                for (float[] kb : keep) {
                    if (kb[0] == b[0] && iou(kb, b) > iouThr) { dup = true; break; }
                }
                if (dup) continue;
                keep.add(b);
                if (keep.size() >= maxBoxes) break;
            }
            StringBuilder sb = new StringBuilder();
            // Tiempos (ms) al comienzo: «T:modelo,foto,análisis|cajas…» (van al registro de tiempos).
            sb.append("T:").append(t1 - t0).append(',').append(t2 - t1).append(',').append(t3 - t2).append('|');
            int start = sb.length();
            for (float[] b : keep) {
                if (sb.length() > start) sb.append(';');
                sb.append((int) b[0]).append(',').append(b[1]).append(',')
                  .append(b[2] / W).append(',').append(b[3] / H).append(',')
                  .append(b[4] / W).append(',').append(b[5] / H);
            }
            return sb.toString();
        } catch (Throwable e) {
            Log.e(TAG, "detect", e);
            return "ERROR:" + e;
        }
    }
}
