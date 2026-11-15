# Atajo "Cargar gasto" (carga rápida)

Un atajo de iOS que manda una captura de pantalla (por ejemplo, un comprobante de Mercado Pago o de tu banco) al backend, lee el gasto y te pregunta qué hacer. **Nada se crea sin que lo confirmes**: el lector (LLM) sugiere, vos decidís.

El atajo es "tonto" a propósito: los textos y las opciones del menú vienen armados del backend (`summary`, `warning`, `actions[].label`, `message`), así que si cambia la lógica no hay que tocar el atajo.

## Antes de armarlo

1. Entrá a la app (PWA) y generá el **código de conexión** del atajo (Perfil, sección del atajo). Se muestra **una sola vez**; copialo.
   - Formato: `<URL del API>|<token>`, por ejemplo `https://shared-expense-manager.onrender.com|jrn_Ab3x...`. La URL es la del API del entorno donde lo generaste; el token (`jrn_...`) no vence. Hay uno activo por persona: al regenerarlo, el anterior deja de andar (el atajo viejo responde 401).
   - El token no es un JWT: solo sirve para los endpoints de `/quick-capture`. El atajo manda únicamente el token (`Authorization: Bearer <token>`); la URL nunca va en un query string ni hay que tipearla.

Las respuestas vienen envueltas: `{ "data": ... }`, en camelCase. Los errores vienen como `{ "detail": "..." }` de FastAPI.

## Pasos del atajo

Receta armada y probada en un iPhone (iOS en inglés). Cada acción va con su nombre en inglés y, entre paréntesis, en español. Al armarlo vos no hay pregunta de importación: eso es sólo para publicarlo (ver más abajo).

1. **Text** (Texto) con el código de conexión que pegás desde el perfil (`https://…|jrn_…`).
2. **Split Text** (Dividir texto) por **Custom** (separador personalizado) `|`.
3. **Get Item from List** (Obtener elemento de la lista): **First Item** de Split Text, y **Set Variable** (Establecer variable) `servidor`.
4. **Get Item from List**: **Last Item** de **Split Text**. Tocá la parte azul, **Select Variable** y elegí la acción Split Text, porque por defecto agarra la variable anterior. **Set Variable** `token`.
5. **Take Screenshot** (Tomar captura de pantalla).
6. **Resize Image** (Cambiar tamaño de imagen) a ancho `1280` (alto automático).
7. **Convert Image** (Convertir imagen) a `JPEG`. Mantiene el peso bien debajo del tope de 8 MB del backend.
8. **Get Contents of URL** (Obtener contenido de URL):
   - URL: chip `servidor` + `/api/v1/quick-capture`
   - Método: `POST`
   - Encabezado: `Authorization` = `Bearer ` (con espacio) + chip `token`
   - Cuerpo de la solicitud: **Form** (Formulario), **Add new field**, tipo **File** (Archivo), clave `file`, valor **Converted Image**.

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

9. **Get Dictionary Value** (Obtener valor del diccionario) clave `data` en Contents of URL, y **Set Variable** `respuesta`.
10. **Get Dictionary Value** clave `draftId` en `respuesta`, y **Set Variable** `borrador`.
11. **Get Dictionary Value** clave `summary` en `respuesta`, y **Set Variable** `resumen`.
12. **Get Dictionary Value** clave `message` en `respuesta`, y un **If** (Si): Dictionary Value **has any value** (tiene algún valor). Adentro: **Show Notification** (Mostrar notificación) con ese Dictionary Value y **Stop This Shortcut** (Detener este atajo). Cerrá con **End If**.

    Por qué: `message` sólo viene cuando no se pudo leer la captura (`status` `"unreadable"`: el borrador queda guardado sin monto y te llega un push). Comparar con texto no se ofrece para valores de diccionario en algunas versiones de iOS; "has any value" sí.
13. **Get Dictionary Value** clave `actions` en `respuesta`, y **Set Variable** `opciones`.
14. **Repeat with Each** (Repetir con cada) item en `opciones`. Adentro: **Get Dictionary Value** clave `label` en **Repeat Item**, y **Add to Variable** (Añadir a variable) `etiquetas`. Cerrá con **End Repeat**.
15. **Get Dictionary Value** clave `warning` en `respuesta`, y un **Text** (Texto): chip `resumen`, un salto de línea y el chip Dictionary Value (el aviso; viene vacío cuando no hay un gasto parecido).
16. **Choose from List** (Elegir de la lista) `etiquetas`, con **Prompt** = el Text del paso 15. (No uses "Elegir del menú": sus ítems son fijos al armar el atajo y acá son dinámicos.)
17. Un **segundo Repeat with Each** item en `opciones` (asegurate de que apunte a `opciones`). Adentro:
    1. **Get Dictionary Value** clave `label` en Repeat Item.
    2. **Text** con ese Dictionary Value (lo convierte en texto, así el If ofrece "is").
    3. **If** Text **is** **Chosen Item** (en algunas versiones de iOS se llama "Selected Item"). Adentro: **Set Variable** `elegida` con el Repeat Item. **End If**.

    Cerrá con **End Repeat**.
18. **Get Dictionary Value** clave `action` en `elegida`, un **Text** con ese valor, y **Set Variable** `accion`.
19. **If** `accion` **is** `confirm` (escrito a mano): **Get Dictionary Value** `groupId` en `elegida`; **Get Contents of URL** a chip `servidor` + `/api/v1/quick-capture/` + chip `borrador` + `/confirm`, `POST`, mismo encabezado `Authorization`, cuerpo **JSON** con un campo **Number** (Número) clave `groupId` = ese Dictionary Value; **Get Dictionary Value** `data` en ese Contents of URL; **Get Dictionary Value** `message` en él; **Show Notification** con ese valor. **End If**. Crea el gasto en ese grupo: división igual entre todos los miembros actuales, pagás vos.
20. **If** `accion` **is** `keep`: **Get Contents of URL** a chip `servidor` + `/api/v1/quick-capture/` + chip `borrador` + `/keep`, `POST`, mismo encabezado, sin cuerpo; después `data`, `message` y **Show Notification**. **End If**. Lo deja en borradores para revisarlo en la app (te llega un push).
21. **If** `accion` **is** `discard`: **Get Contents of URL** a chip `servidor` + `/api/v1/quick-capture/` + chip `borrador`, método **DELETE**, mismo encabezado; después `data`, `message` y **Show Notification**. **End If**. Borra el borrador y su imagen.
22. **Asignarlo a Toque posterior** (ver abajo).

En los tres casos la respuesta es `{ "data": { "message": "..." } }`. Errores que vas a ver:

- `401`: token revocado o regenerado; generá un código nuevo y pegalo en el paso 1.
- `404`: el borrador no existe o no es tuyo.
- `409`: ya estaba resuelto (por ejemplo, tocaste dos veces) o el mes de ese gasto ya está saldado en el grupo elegido. No se crea nada; en el caso del mes saldado el borrador sigue pendiente.
- `400`: el archivo no es una imagen o está vacío (no se guarda nada); en confirmar, el borrador no tiene monto, "Ese grupo no está disponible", o se quiso cargar un gasto en crédito en un grupo de una sola vez.

## Si algo falla

- Las claves distinguen mayúsculas, y la **I** de `draftId` y `groupId` es una i mayúscula: en el teclado del iPhone se ve igual que una ele minúscula. Si un valor sale vacío, reescribila.
- Si armaste un paso copiando otro, sus chips pueden seguir apuntando a las acciones del original (por ejemplo, el **Get Contents of URL** de una rama apuntando al pedido de la rama `confirm`). El síntoma es una notificación con sólo el título "Notification" y sin texto. Con **Select Variable**, repuntá cada chip a la acción de su misma rama.
- Para ver qué contestó el servidor, sumá temporalmente **Show Content** (Mostrar contenido) de Contents of URL después del pedido. Un error viene como `{"detail": "…"}`. Si dice sólo "Not Found", la URL está mal (por ejemplo, un `borrador` vacío deja `//`).
- `401`: generá un código nuevo en el perfil y pegalo en el paso 1. `409`: mes saldado o borrador ya resuelto.

## Asignarlo a Toque posterior

Para dispararlo con un doble o triple toque en la parte de atrás del teléfono:

1. Ajustes (Settings) → Accesibilidad (Accessibility) → Tocar (Touch) → **Toque posterior** (Back Tap).
2. Elegí **Doble toque** (Double Tap) o **Triple toque**.
3. En la sección **Atajos**, elegí **Cargar gasto**.

Así, desde cualquier pantalla, con un doble toque se saca la captura y arranca el flujo.

## Publicar el atajo

Se hace **una sola vez**, cuando el atajo ya anda: en los detalles del atajo, configurá una **pregunta de importación** (import question) sobre la acción **Text** del paso 1, para que quien lo instale tenga que pegar su propio "Código de conexión". Después, **Compartir → Copiar enlace de iCloud**. Ese enlace es genérico (no lleva ningún código adentro) y sirve para todos los usuarios y todos los entornos. Cargalo una vez como `VITE_SHORTCUT_URL` en el host del frontend y redeployá una vez; desde ahí la app muestra "Instalar el atajo" con ese link.

## Seguridad: no compartas el atajo con el código puesto

El código de conexión (con tu token adentro) queda guardado dentro del atajo. Si lo compartís (AirDrop, enlace de iCloud, mensaje) **ya con tu código pegado**, quien lo reciba puede cargar gastos a tu nombre. Antes de compartirlo, borrá el valor del código (o armá una copia limpia): el enlace que se publica tiene que salir de una copia sin código. Si compartiste uno por error, regenerá el código desde la app: el token anterior queda revocado al instante.

## Superficie del API que usa

| Endpoint | Auth | Uso |
|---|---|---|
| `POST /api/v1/quick-capture` | token del atajo | multipart `file`; guarda el borrador y lee la imagen |
| `POST /api/v1/quick-capture/{draftId}/confirm` | token del atajo | `{"groupId"}`; crea el gasto |
| `POST /api/v1/quick-capture/{draftId}/keep` | token del atajo | deja el borrador pendiente + push |
| `DELETE /api/v1/quick-capture/{draftId}` | token del atajo | descarta |
| `POST /api/v1/drafts` | JWT | "Dejar para después" desde la app: multipart `file`, responde 201 con el borrador, sin push |
| `GET/POST/DELETE /api/v1/members/me/shortcut-token` | JWT | estado / emitir (se muestra una vez) / revocar |
