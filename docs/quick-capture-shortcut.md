# Atajo "Cargar gasto" (carga rápida)

Un atajo de iOS que manda una captura de pantalla (por ejemplo, un comprobante de Mercado Pago o de tu banco) al backend, lee el gasto y te pregunta qué hacer. **Nada se crea sin que lo confirmes**: el lector (LLM) sugiere, vos decidís.

El atajo es "tonto" a propósito: los textos y las opciones del menú vienen armados del backend (`summary`, `warning`, `actions[].label`, `message`), así que si cambia la lógica no hay que tocar el atajo.

## Antes de armarlo

1. Entrá a la app (PWA) y generá el **token del atajo** (Perfil, sección del atajo). Se muestra **una sola vez**; copialo.
   - Formato: `jrn_...`. No vence. Hay uno activo por persona: al regenerarlo, el anterior deja de andar (el atajo viejo responde 401).
   - No es un JWT: solo sirve para los endpoints de `/quick-capture`.
2. Tené a mano la URL base del backend (`{BASE}`, por ejemplo `https://<tu-backend>`).

Las respuestas vienen envueltas: `{ "data": ... }`, en camelCase. Los errores vienen como `{ "detail": "..." }` de FastAPI.

## Pasos del atajo

1. **Pregunta de importación "Token"** (tipo texto). Al importar el atajo, Atajos te pide pegar tu token. Queda guardado dentro del atajo.
2. **Tomar captura de pantalla**. Además, en los ajustes del atajo activá "Mostrar en la hoja de compartir" con entrada de tipo **Imágenes**, para poder mandarle una foto o captura ya hecha (si no hay entrada, toma la captura).
3. **Cambiar tamaño de imagen** a ancho `1280`, y después **Convertir imagen** a `JPEG`. Mantiene el peso bien debajo del tope de 8 MB del backend.
4. **Obtener contenido de URL**:
   - URL: `{BASE}/api/v1/quick-capture`
   - Método: `POST`
   - Encabezado: `Authorization` = `Bearer ` + variable **Token**
   - Cuerpo de la solicitud: **Formulario**, un campo de tipo Archivo llamado `file` con la imagen convertida.

   Respuesta (`data`). Todos los textos (`summary`, `warning`, `label`, `message`) los arma el backend; `actions` trae hasta 2 opciones de grupo (`confirm`) más `keep` y `discard`:

   ```json
   {
     "draftId": 12,
     "status": "read",
     "summary": "🛒 Verdulería · $4.500 · pagaste vos · débito",
     "warning": "⚠️ Parecido a uno que ya cargaste: $4.500 Verdulería",
     "actions": [
       { "label": "Fran y Guada · $2.250 c/u", "action": "confirm", "groupId": 3 },
       { "label": "Personal · todo tuyo", "action": "confirm", "groupId": 9 },
       { "label": "Editar en la app", "action": "keep", "groupId": null },
       { "label": "Cancelar", "action": "discard", "groupId": null }
     ],
     "message": null
   }
   ```

   `warning` es `null` cuando no hay nada parecido. **El atajo ramifica siempre por `action`, nunca por el texto del `label`**: los labels cambian según el grupo, el monto y el copy.

5. **Si `data.status` es `"unreadable"`**: no se pudo leer. El borrador queda guardado sin monto (y te llega un push). Hacé **Mostrar notificación** con `data.message` y **Detener** el atajo.
6. **Elegir de la lista** (no "Elegir del menú": sus ítems son fijos al armar el atajo y acá son dinámicos). Receta:
   1. **Repetir con cada uno** de `data.actions`: **Agregar a variable** `etiquetas` con el `label` de cada uno.
   2. **Elegir de la lista** `etiquetas`, con prompt `data.summary` (y, si `data.warning` no es nulo, un salto de línea y `data.warning`). Guarda la elección como `elegido`.
   3. **Repetir con cada uno** de `data.actions` otra vez: **Si** `label` es igual a `elegido`, **Establecer variable** `accion` = `action` y `grupo` = `groupId`.

   Esta receta todavía no se verificó en un dispositivo; probala antes de darla por buena.
7. **Según `accion`** (un **Si** por valor), un **Obtener contenido de URL** más, con el mismo encabezado `Authorization`:
   - `confirm`: `POST {BASE}/api/v1/quick-capture/{draftId}/confirm`, cuerpo JSON `{"groupId": <grupo>}`. Crea el gasto en ese grupo: división igual entre todos los miembros actuales, pagás vos.
   - `keep`: `POST {BASE}/api/v1/quick-capture/{draftId}/keep`. Lo deja en borradores para revisarlo en la app (te llega un push).
   - `discard`: `DELETE {BASE}/api/v1/quick-capture/{draftId}`. Borra el borrador y su imagen.

   En los tres casos la respuesta es `{ "data": { "message": "..." } }`.
8. **Mostrar notificación** con `data.message`. Si la solicitud falló (código distinto de 2xx), mostrá el `detail` del error. Casos que vas a ver:
   - `401`: token revocado o regenerado; generá uno nuevo y actualizá el atajo.
   - `404`: el borrador no existe o no es tuyo.
   - `409`: ya estaba resuelto (por ejemplo, tocaste dos veces) o el mes de ese gasto ya está saldado en el grupo elegido. No se crea nada; en el caso del mes saldado el borrador sigue pendiente.
   - `400`: el archivo no es una imagen o está vacío (no se guarda nada); en confirmar, el borrador no tiene monto, "Ese grupo no está disponible", o se quiso cargar un gasto en crédito en un grupo de una sola vez.

## Asignarlo a Toque posterior

Para dispararlo con un doble o triple toque en la parte de atrás del teléfono:

1. Ajustes, Accesibilidad, Tocar, **Toque posterior**.
2. Elegí **Doble toque** (o **Triple toque**).
3. En la sección **Atajos**, elegí **Cargar gasto**.

Así, desde cualquier pantalla, con un doble toque se saca la captura y arranca el flujo.

## Seguridad: no compartas el atajo con el token puesto

El token queda guardado dentro del atajo. Si lo compartís (AirDrop, enlace de iCloud, mensaje) **ya con tu token pegado**, quien lo reciba puede cargar gastos a tu nombre. Antes de compartirlo, borrá el valor del token (o armá una copia limpia). Si compartiste uno por error, regenerá el token desde la app: el anterior queda revocado al instante.

## Superficie del API que usa

| Endpoint | Auth | Uso |
|---|---|---|
| `POST /api/v1/quick-capture` | token del atajo | multipart `file`; guarda el borrador y lee la imagen |
| `POST /api/v1/quick-capture/{draftId}/confirm` | token del atajo | `{"groupId"}`; crea el gasto |
| `POST /api/v1/quick-capture/{draftId}/keep` | token del atajo | deja el borrador pendiente + push |
| `DELETE /api/v1/quick-capture/{draftId}` | token del atajo | descarta |
| `POST /api/v1/drafts` | JWT | "Dejar para después" desde la app: multipart `file`, responde 201 con el borrador, sin push |
| `GET/POST/DELETE /api/v1/members/me/shortcut-token` | JWT | estado / emitir (se muestra una vez) / revocar |
