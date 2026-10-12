package org.rubus.fenorubus;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.util.Log;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.FrameLayout;

/**
 * Cuadro de texto NATIVO de Android para escribir con el teclado del teléfono
 * (autocorrector, sugerencias, dictado por voz, copiar/pegar del sistema).
 * Todo se arma aquí, en Java y en el hilo de interfaz; Python solo recibe el resultado.
 */
public class NativeInput {
    public interface Callback {
        void onShown();
        void onResult(String text);
        void onError(String error);
    }

    public static void show(final Activity act, final String title, final String text,
                            final int inputType, final boolean multiline, final Callback cb) {
        act.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    final EditText field = new EditText(act);
                    field.setInputType(inputType);
                    if (multiline) {
                        field.setMinLines(3);
                        field.setMaxLines(8);
                    } else {
                        field.setSingleLine(true);
                    }
                    field.setText(text == null ? "" : text);
                    field.setSelection(field.getText().length());
                    int pad = (int) (20 * act.getResources().getDisplayMetrics().density);
                    FrameLayout frame = new FrameLayout(act);
                    frame.setPadding(pad, pad / 2, pad, 0);
                    frame.addView(field);
                    AlertDialog dialog = new AlertDialog.Builder(act)
                            .setTitle(title)
                            .setView(frame)
                            .setPositiveButton("Aceptar", new DialogInterface.OnClickListener() {
                                @Override
                                public void onClick(DialogInterface d, int which) {
                                    cb.onResult(field.getText().toString());
                                }
                            })
                            .setNegativeButton("Cancelar", null)
                            .create();
                    if (dialog.getWindow() != null) {
                        dialog.getWindow().setSoftInputMode(
                                WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE);
                    }
                    dialog.show();
                    field.requestFocus();
                    cb.onShown();
                } catch (Throwable t) {
                    Log.e("NativeInput", "No se pudo abrir el cuadro de texto", t);
                    cb.onError(t.toString());
                }
            }
        });
    }
}
