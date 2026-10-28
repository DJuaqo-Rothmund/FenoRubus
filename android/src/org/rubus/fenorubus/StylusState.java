package org.rubus.fenorubus;

import android.app.Activity;
import android.util.Log;
import android.view.MotionEvent;
import android.view.View;

import java.lang.reflect.Field;

/**
 * Estado del lápiz (S-Pen o similares) para el modo lápiz del cuaderno.
 *
 * Kivy recibe los toques del lápiz como cualquier dedo (con presión), pero no el botón
 * lateral ni la punta de goma. install() pone un filtro delante de la vista de SDL que
 * anota ese estado y luego entrega el toque igual que antes; la app lo consulta con
 * erasing() al tocar la hoja.
 *
 * Los Samsung antiguos, con el botón apretado, mandan acciones propias (211–214) que SDL
 * no conoce y descartaría: se convierten a las normales (bajar, subir, mover, cancelar).
 */
public class StylusState {
    private static final String TAG = "StylusState";
    private static final int SAMSUNG_PEN_DOWN = 211;   // 211 bajar, 212 subir, 213 mover, 214 cancelar
    private static final int BUTTONS = MotionEvent.BUTTON_STYLUS_PRIMARY
            | MotionEvent.BUTTON_STYLUS_SECONDARY | MotionEvent.BUTTON_SECONDARY;

    private static volatile boolean button = false;
    private static volatile boolean eraserTip = false;
    private static volatile boolean stylus = false;
    private static volatile boolean installed = false;

    /** Botón del lápiz apretado o punta de goma: el trazo borra. */
    public static boolean erasing() {
        return button || eraserTip;
    }

    /** El último toque fue de un lápiz (no un dedo). */
    public static boolean isStylus() {
        return stylus;
    }

    private static void update(MotionEvent e) {
        int tool = e.getToolType(e.getActionIndex());
        stylus = tool == MotionEvent.TOOL_TYPE_STYLUS || tool == MotionEvent.TOOL_TYPE_ERASER;
        eraserTip = tool == MotionEvent.TOOL_TYPE_ERASER;
        int action = e.getActionMasked();
        boolean samsung = action >= SAMSUNG_PEN_DOWN && action <= SAMSUNG_PEN_DOWN + 3;
        button = samsung || (e.getButtonState() & BUTTONS) != 0;
    }

    /** Pone el filtro delante de la vista de SDL (una sola vez). true si quedó puesto. */
    public static boolean install(final Activity act) {
        if (installed) {
            return true;
        }
        try {
            Class<?> sdl = Class.forName("org.libsdl.app.SDLActivity");
            Field f = sdl.getDeclaredField("mSurface");
            f.setAccessible(true);
            final View surface = (View) f.get(null);
            if (!(surface instanceof View.OnTouchListener)) {
                return false;
            }
            final View.OnTouchListener sdlTouch = (View.OnTouchListener) surface;
            installed = true;
            act.runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    surface.setOnTouchListener(new View.OnTouchListener() {
                        @Override
                        public boolean onTouch(View v, MotionEvent e) {
                            update(e);
                            int action = e.getActionMasked();
                            if (action >= SAMSUNG_PEN_DOWN && action <= SAMSUNG_PEN_DOWN + 3) {
                                MotionEvent copy = MotionEvent.obtain(e);
                                int[] map = {MotionEvent.ACTION_DOWN, MotionEvent.ACTION_UP,
                                        MotionEvent.ACTION_MOVE, MotionEvent.ACTION_CANCEL};
                                copy.setAction(map[action - SAMSUNG_PEN_DOWN]);
                                try {
                                    return sdlTouch.onTouch(v, copy);
                                } finally {
                                    copy.recycle();
                                }
                            }
                            return sdlTouch.onTouch(v, e);
                        }
                    });
                }
            });
            return true;
        } catch (Throwable e) {
            Log.w(TAG, "Sin lectura del botón del lápiz: " + e);
            return false;
        }
    }
}
