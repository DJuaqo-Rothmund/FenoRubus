package org.rubus.fenorubus;

import android.app.Activity;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Timer;

/**
 * Pantalla de carga animada (Lottie) bajo control de la app.
 *
 * python-for-android quita la pantalla de carga 5 s después de que arranca Python, esté
 * lista la app o no. hold() cancela ese temporizador para que la animación nativa siga a la
 * vista mientras la app precarga todo detrás; luego la app la quita (removeLoadingScreen)
 * en el momento justo. lottieFrame() dice en qué cuadro va la animación para que el logo
 * de la app continúe desde ahí sin que se note el cambio.
 */
public class SplashHold {
    private static final String TAG = "SplashHold";

    private static Field findField(Class<?> cls, String name) throws NoSuchFieldException {
        for (Class<?> c = cls; c != null; c = c.getSuperclass()) {
            try {
                return c.getDeclaredField(name);
            } catch (NoSuchFieldException e) {
                // sigue con la superclase
            }
        }
        throw new NoSuchFieldException(name);
    }

    /** Cancela el retiro automático de la pantalla de carga. true si lo logró. */
    public static boolean hold(Activity act) {
        try {
            Field f = findField(act.getClass(), "loadingScreenRemovalTimer");
            f.setAccessible(true);
            synchronized (act) {
                Timer timer = (Timer) f.get(act);
                if (timer != null) {
                    timer.cancel();
                }
                // Un temporizador sin tareas: así p4a no programa otro retiro.
                f.set(act, new Timer(true));
            }
            return true;
        } catch (Throwable e) {
            Log.w(TAG, "No se pudo retener la pantalla de carga: " + e);
            return false;
        }
    }

    /** Cuadro actual de la animación Lottie, o -1 si ya no está a la vista. */
    public static int lottieFrame() {
        try {
            Class<?> pa = Class.forName("org.kivy.android.PythonActivity");
            View v = (View) pa.getField("mLottieView").get(null);
            if (v == null) {
                return -1;
            }
            View lottie = v;
            if (v instanceof ViewGroup && ((ViewGroup) v).getChildCount() > 0) {
                lottie = ((ViewGroup) v).getChildAt(0);
            }
            Method m = lottie.getClass().getMethod("getFrame");
            Object frame = m.invoke(lottie);
            return frame instanceof Number ? ((Number) frame).intValue() : -1;
        } catch (Throwable e) {
            return -1;
        }
    }
}
