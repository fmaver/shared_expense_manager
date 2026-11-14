# Carga rápida: atajo de iOS, borradores y pegar captura

Fecha: 2026-11-13 · Estado: diseño, para aprobar · Mockups: https://claude.ai/artifact/HAKsxmdE2NRKJc59vLDc28
(ilustrativos; ver "UI" sobre qué componentes reales usar)

## Por qué

Cargar un gasto a mano da pereza en el momento del pago. Antes estaba resuelto con el bot de
WhatsApp: screenshot → compartir a WhatsApp sin guardarlo → el bot lo leía y lo creaba. El bot
está apagado (`WHATSAPP_ENABLED=false`, por los costos de Meta). La PWA no puede reemplazarlo
en el menú de compartir: **iOS Safari no soporta Web Share Target**, así que una PWA instalada
nunca aparece en la hoja de compartir del iPhone.

La meta es volver a cargar un gasto en segundos, desde el momento del pago, sin que la captura
quede guardada en la galería, y sin perder control: **la lectura de la imagen la hace un LLM, a
veces se equivoca, y esto es plata. Nada se crea sin que una persona lo confirme.** Ese principio
ya rige `expense_draft_service.py` y se mantiene.

## Qué se construye (tres piezas que encajan)

1. **Atajo de iOS "Cargar gasto"** con confirmación en el momento, sin abrir la app.
2. **Borradores**: gastos leídos pero no confirmados, que se acumulan y se terminan en la app.
3. **Pegar captura** dentro de la app (flujo de foto que ya existe, con otra fuente de imagen).

El borrador es el puente: todo lo que el atajo no crea en el momento termina ahí.

## Objetivos

- El caso común (débito, pagaste vos, uno de tus dos grupos más usados, división en partes
  iguales) se crea en ~3 toques sin abrir la PWA.
- El caso "la app sugirió el grupo equivocado" se resuelve en el mismo menú, sin pasar por
  borradores.
- Lo que necesita más ajuste (cuotas, división desigual, otro grupo, monto mal leído) queda como
  borrador y nunca se pierde.
- Cualquier usuario puede configurar el atajo desde su perfil desde el día uno.

## No objetivos

- Leer notificaciones de otras apps para detectar pagos solos (imposible en iOS; descartado).
- Reenvío de mails del banco (SendGrid Inbound Parse) — posible fase futura, no ahora.
- Bot de Telegram, app nativa / extensión de compartir.
- **Login persistente / sesión sin vencimiento**: proyecto aparte (mover `SECRET_KEY` a env var
  + refresh token). Este diseño no lo necesita y no lo toca.
- Web Share Target para Android: casi gratis y útil, pero fuera de este alcance (ver "Después").

## Anti-objetivos (sería un fracaso aunque funcione)

- Que un gasto se cree sin confirmación explícita.
- Que la captura termine en la galería del usuario por el flujo del atajo.
- Que un token del atajo filtrado permita ver balances, editar o borrar gastos.
- Que un borrador sea visible para los otros miembros del grupo antes de confirmarse.
- Mockups/pantallas con componentes inventados: se usan los de la app (`FloatingTabBar`, la hoja
  de nuevo gasto, `ScanReview`, etc.).

---

## Flujo 1 — Atajo con confirmación

1. El usuario hace doble toque atrás (Accesibilidad → Toque posterior, asignado al atajo) o
   ejecuta el atajo desde la hoja de compartir con una imagen.
2. El atajo saca la captura (acción "Tomar captura de pantalla", no se guarda en Fotos), la
   **reduce** (≈1280 px de ancho, JPEG) y la manda con el token personal.
3. El backend la lee con el parser existente (`build_expense_draft`), **guarda un borrador** y
   devuelve el resumen y las opciones. No crea el gasto. Tarda ~3–5 s; el atajo muestra su
   indicador nativo mientras tanto.
4. El atajo muestra un menú nativo de iOS:

   ```
   🛒 Supermercado La Esquina · $5.000 · pagaste vos · débito
   [Fran y Guada · $2.500 c/u]     ← grupo sugerido, primero
   [Personal · todo tuyo]
   [Editar en la app]
   [Cancelar]
   ```

5. Según el botón, el atajo llama a:
   - **un grupo** → confirma el borrador en ese grupo → se crea el gasto → aviso "Gasto creado".
   - **Editar en la app** → el borrador queda pendiente → aviso "Guardado en borradores" (+ push
     de pendientes).
   - **Cancelar** → descarta el borrador.
6. Si la lectura falla (no es imagen, no se encontró monto, error de Gemini): el borrador se
   guarda igual **con la imagen** y el atajo avisa "No pude leerla, quedó en borradores". Nada se
   pierde.

**Por qué "Editar" no abre la PWA:** desde un atajo, abrir una URL lanza Safari, no la PWA
instalada (mismo límite iOS que con los links de invitación). Por eso guarda borrador y el push
—que sí abre la PWA al tocarlo— lleva a la lista.

### Las opciones de grupo

- Son los **dos grupos no archivados** donde el usuario más cargó gastos (como pagador) en los
  últimos 90 días; con un solo grupo, aparece uno. Si no tiene historial, los dos primeros por
  orden de creación. *(Ventana de 90 días: decisión del diseñador.)*
- **El grupo personal compite como cualquier otro** por esos dos lugares: no se agrega siempre.
  Para quien carga en Fran y Guada y en Personal, son esos dos; para quien usa dos grupos
  compartidos y casi nunca el personal, Personal no aparece (va por "Editar").
- **Cuotas y grupos de una sola vez:** el backend rechaza crédito en grupos `one_time`
  (`ExpenseService._assert_payment_type_allowed`). Si el borrador tiene `payment_type=credit`,
  los grupos `one_time` **no se ofrecen** como botón, y si queda con menos de dos opciones el
  siguiente más usado ocupa el lugar. *(Decisión del diseñador.)*
- **Posible duplicado:** antes de responder se corre el mismo chequeo de gastos parecidos que ya
  usa el alta (`/expenses/similar`) contra cada grupo ofrecido. Si hay coincidencia, el resumen
  suma una línea "⚠️ Parecido a uno que ya cargaste hoy: $5.000 Supermercado". **No bloquea**: los
  botones siguen iguales. Dos capturas del mismo pago dan dos borradores; esta línea es lo que
  evita crear dos gastos sin darse cuenta. *(Decisión del diseñador.)*
- **Cuál va primero** (el sugerido): el grupo donde el usuario cargó más gastos de la **misma
  categoría** que la leída en los últimos 90 días, entre esos dos; empate o sin datos → el más
  usado. Regla simple a propósito; se puede mejorar después sin cambiar el contrato.
- **El resumen y la división se calculan por grupo.** Los grupos no tienen división por defecto
  guardada, así que se usa `equal` entre **todos los miembros actuales** del grupo (lo mismo que
  hace el alta manual por defecto). El texto de cada botón muestra el resultado:
  - grupo personal → "Personal · todo tuyo"
  - grupo de N miembros → "<nombre> · $<monto/N> c/u" (redondeo como `EqualSplit`).
  - USD → montos en USD tal cual se leyeron ("US$ 12,50 c/u"); la conversión a ARS sigue siendo
    asunto del balance, no del atajo.
- Pagador: siempre el dueño del token. Tipo de pago, cuotas, fecha, moneda, categoría y
  descripción: los que leyó el parser. Si el parser detectó cuotas (>1), el resumen lo dice
  ("crédito · 3 cuotas") y los botones de grupo siguen disponibles.

## Flujo 2 — Borradores

Un **borrador** es un gasto leído y no confirmado, **privado de su dueño**.

Entra a borradores: "Editar en la app" desde el atajo, una lectura fallida, y un borrador que el
atajo dejó a medias (p. ej. el usuario cerró el menú sin elegir — el borrador ya estaba guardado
en el paso 3, así que queda pendiente sin hacer nada más).

> Consecuencia de guardar en el paso 3: cerrar el menú del atajo (deslizar, bloquear el
> teléfono) **no pierde** el gasto. Es intencional.

Dónde se ve:

- **Push** "Tenés N gastos para revisar" con un resumen corto de los primeros. Usa un `tag` fijo
  para que cada nuevo **reemplace** al anterior en vez de apilar avisos. Se envía cuando un
  borrador queda pendiente (no cuando se crea y se confirma en el mismo atajo). Si el usuario no
  tiene push, no se manda nada (no mail: es ruido para algo que la app ya muestra). Se manda en
  dos momentos: al llamar `keep` ("Editar en la app") y cuando la lectura falla (el borrador
  queda pendiente sin que el atajo pregunte nada). Si el usuario cierra el menú sin elegir, el
  backend no se entera y **no hay push**: ese borrador aparece en la tarjeta del inicio. No se
  agrega un envío diferido para cubrir ese caso. *(Decisión del diseñador.)* Tocarlo abre
  la PWA en la lista de borradores (respetar `feedback_sw_notification_navigate`: `postMessage`
  al router, no `client.navigate()`).
- **Tarjeta en el inicio** (encima del contenido de la página principal mobile) mientras haya
  pendientes: "N gastos para revisar · el más viejo de hace X" → lleva a la lista.
- **Lista de borradores**: tarjeta por borrador con miniatura, descripción, monto, grupo sugerido,
  pagador y tipo de pago. Acciones:
  - **Confirmar** (solo si el borrador está completo: monto y grupo sugerido válido para su tipo
    de pago) → crea el gasto tal cual en el grupo sugerido, con división `equal`.
  - **Revisar** → primero un **selector de grupo** (fila de chips con los grupos del usuario, el
    sugerido marcado; no es un formulario, es un paso previo) y después el **formulario de alta
    que ya existe para ese tipo de grupo**, pre-cargado como en el flujo de foto de hoy (con
    `ScanReviewNotice` y la pastilla "de la foto"): `AddExpenseDialog` para un grupo compartido,
    `PersonalExpenseSheet` para el personal. Ninguno de los dos gana un selector de grupo propio.
    Cambiar de grupo en el selector vuelve a abrir el formulario que corresponde con los mismos
    datos leídos. Al guardar, el borrador queda `confirmed` y pasa al siguiente ("Guardar y
    seguir"). *(Decisión del diseñador.)*
  - **Completar** (si falta el monto) → igual que Revisar.
  - **Descartar** → borra el borrador y su imagen.
- La lista tiene que ser alcanzable desde la navegación mobile (regla del proyecto: toda ruta
  nueva también en `FloatingTabBar` o desde el inicio). La entrada es la tarjeta del inicio y el
  push; si no hay pendientes, no se muestra nada. *(Cómo encaja en el `FloatingTabBar` existente
  —insignia, ítem del lanzador "+" o solo tarjeta— queda para el builder, sin inventar una barra
  nueva.)*

Vida del borrador:

- Estados: `pending` → `confirmed` (se creó el gasto; se guarda `expense_id`) o `discarded`.
- **La imagen se borra** al confirmar o descartar. Los borradores pendientes **no vencen** solos
  (un gasto olvidado sigue siendo un gasto); la tarjeta del inicio muestra la antigüedad.
- Confirmar es idempotente: confirmar dos veces el mismo borrador no crea dos gastos (lock de fila
  / chequeo de estado en la misma transacción).
- Confirmar crea el gasto por el **mismo camino que `POST /groups/{id}/expenses/`** (validación
  de membresía, expansión de cuotas, `refresh_archived_state`, notificaciones a los otros
  miembros, lock del mes según el gotcha "One balance per month"). No duplicar esa lógica.

## Flujo 3 — Pegar captura en la app

- En la hoja de nuevo gasto (la que ya existe con "Escanear"), una opción **"Pegar captura"**
  que lee la imagen del portapapeles (`navigator.clipboard.read()`, requiere gesto del usuario;
  en iOS Safari aparece el botón de sistema "Pegar").
- Después es idéntico a subir una foto hoy: "Leyendo…" → formulario pre-cargado → guardar. Usa
  `POST /groups/{id}/expenses/parse-image` como está. Pegar **no crea borrador** por sí solo.
- **"Dejar para después"** (agregado el 2026-11-14 a pedido del usuario): mientras lee o con el
  formulario precargado desde una foto o captura pegada, un botón guarda la imagen como borrador
  pendiente (el backend la vuelve a leer con el mismo parser; si falla, queda sin monto) y cierra la
  hoja con el aviso "Guardado en borradores". **Sin push** (ya está en la app); aparece en la
  tarjeta del inicio y en la lista. No aplica a la carga manual (sin foto): guardar un formulario a
  medias quedó fuera.
- Uso esperado: en el editor de capturas de iOS, "Copiar y eliminar" → abrir Jirens → Pegar.
- Si el navegador no expone imágenes del portapapeles o no hay imagen, la opción no aparece o
  muestra un mensaje; no rompe el resto.

## Token del atajo

- Token **opaco** (aleatorio, ≥32 bytes, URL-safe), **no un JWT**: no depende del `SECRET_KEY`
  hardcodeado y se puede revocar.
- Se guarda **hasheado** (SHA-256) con un prefijo visible corto para identificarlo; el valor en
  claro se muestra **una sola vez** al crearlo.
- **Sin vencimiento**, revocable. Uno activo por usuario: generar uno nuevo revoca el anterior.
  Se guarda `last_used_at`.
- **Alcance limitado**: el token solo autentica los endpoints del atajo (subir captura, confirmar
  / dejar pendiente / descartar **sus propios** borradores). No sirve para ningún otro endpoint;
  el `get_current_member` actual no lo acepta.
- Riesgo residual aceptado: si se filtra, alguien puede crear borradores y confirmarlos en los
  grupos del dueño. Mitigaciones: alcance limitado, revocación desde el perfil, "último uso"
  visible.
- Riesgo de producto: compartir un atajo ya configurado comparte el token. El atajo publicado
  (iCloud link) **no lleva token**; lo pide al instalarse (pregunta de importación de Atajos) y
  la pantalla de perfil lo explica.

### Perfil → "Conectar atajo"

- Sin token: botón "Conectar atajo" → genera el token → muestra el token con botón copiar, el
  link de instalación del atajo y pasos cortos (instalar, pegar el token, asignar Toque
  posterior).
- Con token: "Atajo conectado · último uso hace X" + "Desconectar" (revoca) + "Generar uno nuevo".
- No depende de `WHATSAPP_ENABLED` ni de push.

### El atajo en sí

Archivo de Atajos publicado por link de iCloud (lo arma el dueño en su iPhone; no es código del
repo). El repo guarda en `docs/` las instrucciones exactas de cómo está armado (acciones, URL,
headers, cómo usa las respuestas) para poder rehacerlo. La URL base sale del ambiente
(staging/prod); el atajo de prod apunta a prod.

## Backend

Contrato orientativo (nombres finales del builder; respetar el sobre `{data: ...}` y camelCase):

- `POST /api/v1/quick-capture` — multipart con la imagen; auth: token del atajo.
  Guarda el borrador, intenta leerlo y responde:
  ```
  { draftId, status: "read" | "unreadable",
    summary: "🛒 Supermercado La Esquina · $5.000 · pagaste vos · débito",
    options: [ { groupId, label: "Fran y Guada · $2.500 c/u", suggested: true }, ... ] }
  ```
  El texto del resumen y de cada botón lo arma el **backend**, para que el atajo sea tonto y
  cambiar el texto no requiera reinstalarlo.
- `POST /api/v1/quick-capture/{draftId}/confirm` `{ groupId }` — token del atajo. Crea el gasto
  (camino de `create_expense`) y responde el texto del aviso.
- `POST /api/v1/quick-capture/{draftId}/keep` — token del atajo. Lo deja pendiente y dispara el
  push de pendientes. Responde el texto del aviso.
- `DELETE /api/v1/quick-capture/{draftId}` — token del atajo. Descarta.
- Para la PWA (JWT normal): crear un borrador desde una imagen ("Dejar para después"), listar mis borradores pendientes, ver la imagen de uno, confirmar uno
  (con los campos editados del formulario, mismo shape que `ExpenseCreate` + `groupId`),
  descartar.
- Para el perfil (JWT normal): crear/regenerar token, ver estado, revocar.

Datos (migración nueva `m18_…`):

- `expense_drafts`: dueño (`member_id`), estado, campos leídos (todos nullable: monto,
  descripción, categoría, fecha, tipo de pago, cuotas, moneda, confianza), grupo sugerido, imagen
  (bytes + mime, nullable — se pone en null al cerrar), `expense_id` al confirmar, timestamps.
- `shortcut_tokens` (o columnas en `members`, a criterio del builder): hash, prefijo,
  `created_at`, `last_used_at`, `revoked_at`.

Notas para el builder:

- Imagen en la base (bytea) a propósito: el atajo la manda reducida (~200 KB), solo vive mientras
  el borrador está pendiente y no hay storage de archivos hoy. El tope de 8 MB de
  `build_expense_draft` sigue aplicando.
- El push hoy no manda `tag`; hay que sumarlo al payload y a `sw.js` para el reemplazo de avisos.
- Que el gasto confirmado desde el atajo dispare las mismas notificaciones a los otros miembros
  que un alta normal.
- `get_expense` / cascadas de cuotas: confirmar un borrador con cuotas debe expandir filas igual
  que el alta normal.

## UI — regla

Las pantallas nuevas (tarjeta del inicio, lista de borradores, perfil → conectar atajo, opción
"Pegar captura") se construyen con los componentes y tokens existentes ("Cuenta Clara", Manrope,
violeta). La revisión de un borrador **reusa** el formulario de alta y los bloques de
`ScanReview.tsx`; no hay formulario nuevo. Los mockups enlazados muestran el flujo, no los
componentes finales.

## Pruebas que importan

- Confirmar un borrador crea exactamente un gasto aunque se llame dos veces.
- El token del atajo no autentica ningún endpoint fuera de quick-capture; uno revocado da 401.
- Un borrador ajeno no se puede ver, confirmar ni descartar (ni por token ni por JWT).
- La división por grupo: personal → todo del dueño; 2 miembros → 50/50; 3 → partes iguales con el
  redondeo de `EqualSplit`.
- Lectura fallida → borrador `pending` con imagen y sin monto; "Confirmar" no disponible.
- Grupo archivado o del que el usuario ya no es miembro: no aparece como opción y confirmar en él
  falla con un error claro.

## Después (fuera de alcance, anotado)

- Web Share Target en el manifest para Android (la PWA aparece en "compartir").
- Reenvío automático de mails de banco / Mercado Pago a borradores.
- Mejor sugerencia de grupo (por comercio, no solo categoría).
- Login persistente (proyecto aparte).
