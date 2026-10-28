# Ideas pendientes

Ideas conversadas y dejadas para más adelante. Al retomar un tema parecido, recordar la
conversación de origen.

## Botón «Liberar espacio» (fotos de ensayos y predios)

*Conversado el 28/10/2026, al crear «Fotos extra» e IA+.*

Las fotos extra (carpeta «IA+ Conocimiento ampliado») ya se borran solas del teléfono una
vez marcadas. Para las fotos de los ensayos y predios se propuso un botón «Liberar
espacio» que borre del teléfono las que ya están respaldadas en Drive, y que la app las
vuelva a bajar cuando las necesite (línea de tiempo, informes, PDF). Se dejó para más
adelante.

## Subir fotos extra directo desde Google Drive

*Conversado el 28/10/2026, al crear «Fotos extra». Se dejó como está por ahora.*

La app usa el permiso `drive.file`: solo ve lo que ella misma (o la web de PhenoRubus)
subió. Por eso las fotos de afuera se suben con la web («IA+ › Elegir carpeta») o
desde el teléfono. Si más adelante se quiere subirlas con la página de Google Drive:

1. **Selector de Drive (recomendado):** en la web, botón «Autorizar fotos de Drive» que
   abre el selector de Google (Google Picker) en la carpeta; se elige todo (Ctrl+A) y la
   app pasa a verlas. Requiere activar «Google Picker API» y crear una clave de API en
   Google Cloud (unos 5 minutos).
2. **Ampliar el permiso** a ver todo el Drive (`drive.readonly`): automático, pero es un
   permiso restringido (aviso de «app no verificada» y volver a conectar la cuenta en
   todos los equipos).

## Cuenta central de respaldo (todas las cuentas en un solo Drive)

*Conversado el 28/10/2026.*

**Idea:** un correo designado (el del responsable u otro) que reúna las fotos y bases de
datos de todas las cuentas de Google que usan la app, como respaldo general, aparte de lo
que cada usuario ya guarda en su propio Drive.

**Propuesta (sin servidor propio, sin Google Workspace):**

1. **Ajuste en la app:** «Respaldo central: correo» (por ensayo o general). Al activarlo,
   la app comparte con ese correo su carpeta «PhenoRubus · Imágenes de Fenología» (solo
   lectura). El permiso actual (`drive.file`) alcanza: la app puede compartir las carpetas
   que ella creó. El usuario ve y acepta a quién se comparte.
2. **En la cuenta central:** un Google Apps Script (gratis, corre en los servidores de
   Google con un horario, p. ej. cada noche) recorre «Compartidos conmigo», encuentra las
   carpetas de PhenoRubus y **copia** lo nuevo a «PhenoRubus · Respaldo central/<correo del
   usuario>/…». Al copiar, el archivo pasa a ser de la cuenta central: si el usuario borra
   algo en su Drive, la copia central se mantiene (un respaldo de verdad, no solo un
   acceso compartido).
3. **Panel del centralizador** (web): cuántas fotos y registros hay por usuario y por
   ensayo, última copia, espacio usado, y la posibilidad de reunir todo para entrenar IA+
   con las fotos de todas las cuentas.

**Uso principal: una base mayor para entrenar IA+.** Con la cuenta central («usuario
maestro») se reúnen en un solo lugar:

- las fotos de detalle de los ensayos y predios de **todas** las cuentas;
- las fotos extra («IA+ Conocimiento ampliado») de todas las cuentas;
- las marcas de cajas (`marcas.json`) de cada cuenta, que el script junta en una sola
  (por foto gana la marca más reciente, igual que hoy entre teléfono y PC).

El entrenamiento del detector (en el PC o en Colab) lee directo de la carpeta central:
más fotos, más variedades, más lugares y más años, y el modelo resultante (un archivo de
pocos MB) se entrega a todas las apps. Desde la cuenta maestra también se podrían marcar
fotos de cualquier usuario en la web («IA+»), sumando al mismo conjunto.

**A considerar:**

- *Espacio:* la cuenta gratuita trae 15 GB (unas 40 mil fotos de ~350 KB); para más,
  Google One o una cuenta de Workspace.
- *Alternativa con Google Workspace:* una «unidad compartida» de la organización donde
  la app de cada usuario suba una segunda copia; los archivos pertenecen a la unidad (no
  al usuario) y no hace falta el script. Requiere Workspace.
- *Privacidad:* compartir solo con aviso y aceptación del usuario; poder dejar de
  compartir desde Ajustes.
- *Bases de datos:* además de las fotos, los paquetes de sincronización
  («Sincronización/…») y los respaldos diarios de la base ya están en la carpeta, así que
  la copia central incluye los registros completos y se pueden reconstruir en la web.
