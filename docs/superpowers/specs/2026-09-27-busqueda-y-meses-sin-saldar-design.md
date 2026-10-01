# Búsqueda de gastos y meses sin saldar — diseño

Fecha: 27 de septiembre de 2026. Estado: aprobado en conversación, pendiente de revisión escrita.
Abarca los dos repos: `shared_expense_manager` (dos endpoints nuevos) y `shared_expense_front`
(tres lupas, el selector de mes y el filtro "Sin saldar").

## Para qué

Encontrar un gasto sin tener que acordarse del mes ni del grupo ("¿cuándo pagamos la cena en el
centro?", "¿de qué era ese 24.000?", "¿qué pagó Fran?"), y enterarse de si quedó algún mes del
pasado sin saldar.

## Qué se decidió

### Tres lupas

| Lupa | Dónde | Busca en | Implementación |
|---|---|---|---|
| General | Arriba a la derecha en **Grupos** (al lado del avatar) y en **Personal** (en la cápsula) | Todos los grupos del usuario y su grupo personal | Endpoint nuevo |
| Del grupo | En la cápsula de arriba de un grupo, al lado del ⋯ | Todo el historial de ese grupo | El mismo endpoint, con `groupId` |
| Del mes | En la fila de filtros del grupo, en lugar de "Sin saldar", al lado de "Míos" | Los gastos del mes que se está mirando | En el front, sin backend |

### Reglas de coincidencia (las mismas en las tres)

- La búsqueda se parte en palabras; **cada palabra** tiene que aparecer en la descripción **o** en
  el nombre de quien pagó. "cena centro" encuentra "Cena en el centro"; "fran super" encuentra un
  "Supermercado" que pagó Fran.
- **Sin distinguir mayúsculas ni acentos**: "cafe" encuentra "Café". Se normalizan los dos lados
  (minúsculas y `á é í ó ú ü ñ` → `a e i o u u n`).
- Si la búsqueda entera es un número (`24000`, `24.000`, `24000,50`, `24.000,50`), además trae
  los gastos de **exactamente** ese monto (tolerancia ±0,005). El texto sigue buscándose: un gasto
  que tenga "24000" en la descripción también sale.
- Menos de 2 caracteres (y no un número): no se busca.

### Qué entra

- Gastos de los grupos y gastos personales (`expenses`), incluidos los fijos de grupo, que ya
  viven como filas de `expenses`.
- Fijos personales (`recurring_personal_expense_instances`): no tienen fecha ni pagador. Se
  devuelven **sin fecha** (`date: null`), sólo con su período, y el pagador es el dueño del grupo
  personal. Para ordenar cuentan como el comienzo de su mes, pero eso nunca se muestra.
- **Quedan afuera** los ingresos, las transferencias (`prestamo`) y los pagos del saldado
  (`balance`).
- Cuotas: **una fila por cuota**, cada una con su número (`2/6`), su período y su estado. Así se ve
  en qué período entró cada una y si ese período se saldó.

### Alcance y permisos

- La búsqueda general cubre los grupos donde el usuario tiene membresía, **archivados incluidos**
  (el historial sigue siendo suyo), y su grupo personal. Se excluyen grupos con `status = deleted`.
- La del grupo exige membresía: sin ella, `403`.
- Nunca se devuelve un gasto de un grupo donde el usuario no está. Es el test más importante.

### Resultado

Orden: fecha del gasto, de más nueva a más vieja (desempate por id). Un fijo personal, que no
tiene fecha, se ordena como si fuera el comienzo de su período. Tope: **50 resultados**, con
`hasMore` si había más.

Cada resultado trae: `kind` (`expense` | `recurring_personal`), `id`, `description`, `amount`,
`currency`, `date` (`null` en los fijos personales), `category`, `groupId`, `groupName`, `groupType`, `payerId`, `payerName`,
`installmentNo`, `installments`, `periodYear`, `periodMonth` (el mes en que entró: el de su
`monthly_share`), y `periodSettled` (`is_settled` de ese mes; `null` para el grupo personal, que
no se salda).

### Meses sin saldar

Se marca un mes si es **anterior al mes actual**, **no está saldado** y tiene **algún saldo
distinto de cero** (|saldo| > 0,01). Ni el mes actual ni los futuros cuentan: ahí no "se pasó"
nada. Un mes viejo donde todos quedaron en cero tampoco. Los eventos (`one_time`) y el grupo
personal no usan esto.

Se ve **dentro del selector de mes** (el ▼ de la cápsula): los meses pendientes llevan un punto y
arriba de la grilla hay un atajo "Sin saldar: jul 2026 · ago 2026" para saltar directo. No hay
aviso fuera del selector y el selector de grupos no lo muestra.

### El filtro "Sin saldar"

Hoy no filtra por mes saldado: oculta los movimientos internos (`balance` y `prestamo`), y en el
mes actual casi nunca hay. Como el nombre no dice lo que hace, **se saca**, y en su lugar va la
lupa del mes. Los pagos y transferencias vuelven a verse siempre en la lista.

## Backend

### `GET /api/v1/search/expenses?q=<texto>&groupId=<id opcional>`

- Router nuevo `entrypoint/search.py` (prefijo `/search`), registrado en `router.py`.
- `service_layer/search_service.py`: arma las palabras y el monto posible (`parse_query`, función
  pura, con tests unitarios), resuelve los grupos permitidos y llama al repositorio.
- `SearchRepository` en `adapters/repositories.py`, dos consultas:
  1. `expenses` ⨝ `monthly_shares` ⨝ `groups` ⨝ `members` (pagador), filtrada por
     `group_id IN (grupos permitidos)`, `category NOT IN ('balance','prestamo')`, y la
     coincidencia de texto/monto.
  2. `recurring_personal_expense_instances` del grupo personal del usuario, con la coincidencia
     sobre `label` y `amount` (sin pagador: el nombre del dueño también cuenta como pagador, para
     que "fran" encuentre sus fijos).
  Se combinan en Python, se ordenan y se cortan en 50. Cada consulta pide 51 para saber si hay más.
- Normalización de acentos en SQL con `translate(lower(col), 'áéíóúüñ', 'aeiouun')` (también
  `àèìòù` y mayúsculas acentuadas vía `lower`). Sin extensiones (`unaccent` no hace falta) y sin
  migración.
- Esquemas en `domain/schemas/search.py` (`CamelCaseModel`): `ExpenseSearchResult`,
  `ExpenseSearchResponse { results, hasMore }`, envuelto en `ResponseModel`.
- Dependencia `get_search_service` en `dependencies.py`.

### `GET /api/v1/groups/{groupId}/shares/unsettled`

- En `entrypoint/monthly_share.py`. Verifica membresía (`403`).
- Usa `get_all_monthly_shares(group_id)` y filtra en el servicio: anterior al mes actual, no
  saldado, algún |saldo| > 0,01. Devuelve `[{ year, month }]` ordenado del más viejo al más nuevo.
  Para eventos y grupo personal devuelve `[]`.

### Tests

- Unitarios (`make test`): `parse_query` (palabras, acentos, número con y sin separadores, menos de
  2 caracteres); el filtro de meses sin saldar (actual y futuros afuera, saldados afuera, todo en
  cero afuera).
- Integración (`make integration`): coincidencia por descripción, por pagador, por monto exacto,
  sin acentos, multi-palabra; excluye `balance`/`prestamo`; incluye fijos personales, sin fecha y
  con su período; una fila por
  cuota con su período y estado; **un gasto de un grupo ajeno nunca aparece**; `groupId` de un grupo
  ajeno da 403; tope de 50 con `hasMore`; `unsettled` con los casos de arriba.

No hay migración.

## Front

### La búsqueda que se estira

- Al tocar la lupa (general o del grupo), la barra de arriba se transforma en un **campo de vidrio
  a lo ancho** con una ✕ a la derecha, y el teclado se abre (el foco sale del mismo toque). El
  volver se esconde mientras se busca. La ✕ cierra y restaura la pantalla; la ⓧ dentro del campo
  sólo borra.
- **Resultados en vivo**: con 2 letras o un número, con debounce de ~250ms, el contenido de la
  pantalla se reemplaza por los resultados. Sin texto se ve la pantalla normal. Mientras llega la
  respuesta siguen los resultados anteriores (sin parpadeo). Se descartan respuestas viejas que
  lleguen tarde (ver la memoria de carreras en hooks con clave).
- Resultados agrupados por **fecha del gasto** ("8 jun 2026"). Los fijos personales, que no
  tienen fecha, van bajo un encabezado que es sólo el mes ("Septiembre 2026") y su fila dice "Cada
  mes · sep 2026" en lugar de una fecha. Cada fila lleva emoji de categoría,
  descripción (+ `2/6`), "Casa · Pagó Fran" (en la del grupo, sin el grupo), monto, y dos chips: el
  **período** ("jul 2026") y el **estado** ("✓ Saldado" en verde, "Sin saldar" en gris; en rojo suave
  si el período ya pasó). Los gastos personales no llevan chip de estado.
- Tocar un resultado lleva a ese grupo en ese período con el detalle abierto
  (`/groups/:id?year=&month=&expense=:id`); uno personal, a `/personal?year=&month=`.
- Estados: vacío ("Buscá por nombre, monto o quién pagó"), sin resultados ("No encontramos nada con
  '…'"), error con reintento, y "Mostramos los 50 más recientes: refiná la búsqueda".
- Desktop: ⌘K / Ctrl+K abre la misma búsqueda, en la cápsula del encabezado.
- Se borra la pantalla `SearchPage` "Pronto…" y el flag `FEATURE_SEARCH` (ahora hay backend).
  `FEATURE_RECEIPTS` no cambia.

### La lupa del mes

En `ExpenseListHeader`, en lugar del chip "Sin saldar". Se estira dentro de la fila y filtra la
lista del mes en vivo con las mismas reglas (una función compartida `matchesQuery` en el front,
con los mismos casos que `parse_query`). Se combina con "Míos"; la ✕ la cierra.

### Meses sin saldar en el selector

`MonthPager` pide `shares/unsettled` al abrir el selector (no en cada pantalla), marca con un punto
los meses pendientes de la grilla y muestra el atajo arriba. Sólo en grupos regulares.

### Cliente y archivos

- `src/api/search.ts` (`searchExpenses(q, groupId?)`), `getUnsettledMonths(groupId)` en
  `src/api/shares.ts`, tipos en `src/types/expense.ts`.
- Componentes nuevos: `components/search/ExpandingSearch.tsx` (el campo que se estira),
  `components/search/SearchResults.tsx`, `hooks/useExpenseSearch.ts` (debounce + descarte de
  respuestas viejas), `utils/search.ts` (`matchesQuery`).
- Se tocan `FloatingTopBar`, `GroupLayout`, `PersonalDashboard`, `MobileHeader` (lupa en Grupos),
  `ExpenseListHeader`, `MonthPager`, `ExpensesDashboard` (desktop) y los JSON de i18n.

## Fuera de alcance

- Búsqueda de ingresos y transferencias.
- Búsqueda por categoría como filtro aparte (el texto no mira la categoría).
- Índices o búsqueda de texto completo (`tsvector`): el volumen de una casa no lo necesita.
- Aviso de meses sin saldar fuera del selector o en el selector de grupos.
