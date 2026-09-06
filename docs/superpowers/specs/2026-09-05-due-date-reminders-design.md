# Vencimientos de servicios y recordatorios — diseño

**Fecha:** 2026-09-05
**Estado:** aprobado, listo para plan de implementación

## Objetivo

Que un miembro cargue una vez cuándo vence un servicio (luz, gas, internet, streaming,
alquiler) y la app le avise antes de cada vencimiento, sin volver a cargar nada.

## Alcance

Esta es la **fase 1 de tres**. Se construye y se prueba en producción antes de empezar las
siguientes, porque es la única que no depende de nada y porque prueba toda la infraestructura
de scheduling con el payload más simple posible.

| Fase | Contenido | Estado |
|---|---|---|
| **1** | Vencimientos de servicios + job diario + recordatorios | **este documento** |
| 2 | Botón "ya se pagó" → formulario de gasto pre-cargado | diseñada a grandes rasgos, no especificada |
| 3 | Tabla de tarjetas, vencimiento de tarjeta, `card_id` en gastos, monto del resumen | ídem |

**Fuera de alcance en la fase 1**, deliberadamente:

- Tarjetas de crédito. Su fecha se calcula desde el cierre + un offset que carga el usuario
  (decisión ya tomada), pero la fecha sola sirve poco sin el monto del resumen, y el monto
  necesita `card_id` en los gastos. Van juntas o no van.
- Estado de pago. La fase 1 no sabe si pagaste; avisa igual.
- Monto. Llega en la fase 2, donde tiene sentido porque pre-carga el formulario de gasto.

### Advertencia registrada para la fase 3

"Que los gastos en crédito entren por resumen y no al mes siguiente" **es un cambio a lógica
de plata que ya está en producción**. Cambiaría en qué mes caen compras ya cargadas, lo que
mueve balances, incluidos los de meses ya saldados. Es bastante más delicado que agregar una
tabla de tarjetas y necesita su propia discusión sobre qué pasa con lo existente.

## Decisiones de diseño y por qué

### El dueño es siempre un grupo

Las tarjetas irán al grupo personal; los servicios pueden ir a cualquier grupo. Como
`GroupType.PERSONAL` ya existe, **no hacen falta dos tipos de dueño**: una sola FK `group_id`,
y "personal" es apuntar al grupo personal. La regla de a quién se avisa queda uniforme —los
miembros del grupo dueño—, que en un grupo personal es una sola persona.

Alternativa descartada: dueño polimórfico (miembro *o* grupo). Duplicaba la lógica de
destinatarios sin agregar nada que el grupo personal no resuelva.

### Un solo patrón de fecha, no dos

`day_of_month` + `every_n_months` + un mes ancla. Con `every_n_months = 1` sale el caso
mensual, así que no hay ramas en el código: hay una fórmula. El ancla solo importa cuando
N > 1, y es lo que distingue "bimestral empezando en octubre" de "bimestral empezando en
noviembre".

Se soporta bimestral/anual desde el principio porque en Argentina el gas y el ABL suelen ser
bimestrales y el seguro anual. Agregarlo después obligaría a migrar filas ya cargadas.

Descartado el patrón "3er jueves": es propio de cierres de tarjeta, no de vencimientos de
servicios. Entra en la fase 3, donde sí hace falta.

Descartada la fecha única sin repetición: agrega ciclo de vida (¿qué pasa con el vencimiento
después de la fecha?) por un caso que `active = false` cubre razonablemente.

### La tabla de recordatorios es el mecanismo de seguridad, no un log

`UNIQUE(due_date_id, member_id, due_on)` es lo que hace que correr el job de más **no pueda**
duplicar un aviso. Sin esa restricción, cualquier reinicio, deploy o doble ejecución reenvía
la notificación. Con ella, el disparador pasa a ser un detalle intercambiable: loop interno
hoy, cron externo mañana, sin tocar la lógica.

## Modelo de datos

```
due_dates
  id                  int PK
  group_id            FK groups(id) ON DELETE CASCADE
  created_by_member_id FK members(id)
  label               varchar(255)      "Luz", "Netflix"
  category_name       varchar(50)       default "servicios" — lo usa la fase 2 al pre-cargar
  day_of_month        int               1..31
  every_n_months      int               default 1
  anchor_year         int
  anchor_month        int               1..12
  notify_days_before  int               default 3
  active              bool              default true
  created_at          timestamp

due_date_reminders
  id             int PK
  due_date_id    FK due_dates(id) ON DELETE CASCADE
  member_id      FK members(id) ON DELETE CASCADE
  due_on         date          la ocurrencia concreta, no la fecha de envío
  sent_at        timestamp
  UNIQUE(due_date_id, member_id, due_on)
```

Migración `m17_due_dates`, con `down_revision = "m16_push_subscriptions"`.

## Cálculo de la fecha

```
aplica_en(year, month)  ⇔  ((year*12 + month) - (anchor_year*12 + anchor_month)) % every_n_months == 0
                           y (year, month) >= (anchor_year, anchor_month)

ocurrencia(year, month) = date(year, month, min(day_of_month, último_día_del_mes))
```

El `min` es la regla del día 31: en noviembre cae 30, en febrero 28 o 29. Un vencimiento
cargado el 31 no se saltea los meses cortos.

**No se corre por fin de semana ni feriado.** Si la boleta dice 20 y el 20 es domingo, la
boleta sigue diciendo 20; mover la fecha haría que la app muestre un número distinto al del
papel. Además el aviso es *antes* del vencimiento, así que el fin de semana no cambia nada
útil para el usuario.

## El job

Un `asyncio.Task` lanzado en el `lifespan` de la app. Es viable **en producción**, donde
UptimeRobot le pega a `/liveness` cada 5 minutos y el proceso no se duerme.

**Esto es una dependencia real del feature, no un detalle de infraestructura**: si UptimeRobot
deja de pinguear prod, el servicio se apaga a los 15 minutos de inactividad y los recordatorios
dejan de salir sin que nada falle visiblemente. El endpoint `POST /tasks/due-date-reminders`
existe también para eso: permite mover el disparador afuera sin tocar la lógica.

En **staging** UptimeRobot no corre, así que el servicio está apagado casi siempre y el loop no
es confiable ahí. Es esperado, no un bug: staging se prueba con el endpoint manual, y el loop
solo se puede validar de punta a punta en producción o dejando el servicio despierto a través
de un cambio de hora.

**Duerme hasta la próxima hora en punto**, no una hora fija. Con `sleep(3600)` la hora de
envío depende de cuándo arrancó el proceso —un deploy a las 14:37 mueve el aviso a las 09:37—
y sería distinta después de cada deploy. Alineado a :00, la respuesta a "¿a qué hora avisa?"
es una sola: **09:00 de Argentina**.

Eso redefine la ventana 09:00–22:00: no es el horario de envío, es una red de seguridad. Si la
app estuvo caída a las 9 y vuelve a las 14, el aviso sale a las 14 en vez de perderse; si
vuelve a las 3 de la mañana, espera hasta las 9.

En cada vuelta:

1. `hoy` = fecha actual en **America/Argentina/Buenos_Aires**. El server corre en UTC; si se
   usara `date.today()` los vencimientos del día 1 se dispararían el día anterior a las 21hs.
2. Si la hora local está **fuera de 09:00–22:00**, no manda nada y vuelve a dormir. En el curso
   normal esto solo descarta las vueltas de 22:00 a 08:00; el envío real ocurre en la vuelta de
   las 09:00. Un push a las 4 de la mañana por la boleta del gas es cómo se consigue que
   alguien apague las notificaciones para siempre.
3. Para cada `due_date` activo: calcular la próxima ocurrencia. Si
   `(ocurrencia - hoy).days == notify_days_before`, para cada miembro del grupo dueño:
   a. Insertar la fila en `due_date_reminders` (`ON CONFLICT DO NOTHING`). Si no insertó,
      ya se avisó: seguir.
   b. Enviar la notificación.
   c. Si el envío falla, **borrar la fila** para que reintente en la vuelta siguiente.

El orden importa: insertar antes de enviar hace que el modo de falla sea "una hora de demora"
en vez de "notificación duplicada". El borrado en caso de error es lo que evita que ese mismo
orden convierta un fallo transitorio en un aviso perdido para siempre.

### Riesgo aceptado

Si el proceso está caído durante toda la ventana 09:00–22:00 del día que correspondía avisar,
ese aviso se pierde: al día siguiente ya no se cumple `== notify_days_before`. Se acepta
porque UptimeRobot alerta cuando el servicio se cae, así que la falla no es silenciosa.

## Notificaciones

`NotificationService.notify_due_date`, que hereda el ruteo existente: push si el miembro tiene
la app instalada, mail si no. `test_push_wiring_guard.py` **hoy solo escanea `entrypoint/`**, y esta llamada vive en el
service layer, así que no la cubriría. Se amplía el guard a `service_layer/` como parte de este
trabajo: uno de los tres bugs que motivaron el guard (el saldado desde el chatbot) también
estaba fuera de los routers, o sea que el agujero ya existía.

**Destinatarios**: los miembros del grupo dueño que no lo tengan archivado. Se reutiliza
`_notifiable_members`, la misma regla que ya usan las notificaciones de saldado — archivar un
grupo significa "no me interesa más", y sería incoherente que siga mandando recordatorios.
Con `notify_days_before = 0` el aviso sale el mismo día del vencimiento, que es un uso válido.

Texto: `📅 {label} vence en {n} días ({fecha})`, con el nombre del grupo como título, igual
que el resto. Deep link a la pestaña de vencimientos del grupo.

## API

Todo bajo `/api/v1`, con envoltorio `ResponseModel[T]` y camelCase en el cable.

| Método | Ruta | Notas |
|---|---|---|
| `GET` | `/groups/{group_id}/due-dates` | lista los del grupo |
| `POST` | `/groups/{group_id}/due-dates` | crear |
| `PUT` | `/groups/{group_id}/due-dates/{id}` | editar |
| `DELETE` | `/groups/{group_id}/due-dates/{id}` | borrar |
| `POST` | `/tasks/due-date-reminders` | dispara el job. Protegido por secreto compartido |

El endpoint de tareas existe **para poder probar el feature sin esperar un día**, y como
salida de emergencia si el loop interno falla. No usa JWT: no hay usuario detrás. Se protege
con un header `X-Task-Secret` contra una variable de entorno; si la variable no está seteada,
el endpoint responde 404 en vez de quedar abierto.

Permisos: cualquier miembro del grupo puede crear y editar vencimientos, igual que con los
gastos.

## Frontend

- `src/api/dueDates.ts` — cliente nuevo, a mano, como el resto.
- Pestaña "Vencimientos" en `GroupLayout`, junto a Gastos / Miembros / Gráficos / Ajustes.
  La misma pantalla sirve para el grupo personal, así que no hay dos UIs que mantener.
- Formulario: nombre, día del mes, cada cuántos meses, desde qué mes, días de anticipación.

## Testing

**Unitarios** (`make test`, sin DB):

- Cálculo de fecha: día 31 en meses cortos, bisiesto, `every_n_months` con ancla, meses
  anteriores al ancla.
- Predicado "hay que avisar hoy": frontera exacta de `notify_days_before`.
- Zona horaria: un caso a las 21:00 UTC del día anterior debe resolver al día argentino
  correcto.
- Ventana horaria: fuera de 09–22 no envía; a las 09:00 sí.
- Alineación al reloj: el cálculo del sueño devuelve el tiempo hasta el próximo :00, no 3600.
- Ruteo de notificación: push cuando hay dispositivo, mail cuando no.

**Integración** (`make integration`, requiere `TEST_DATABASE_URL`):

- CRUD de los cuatro endpoints, incluido el 403/404 de un grupo ajeno.
- Idempotencia: correr el job dos veces produce **una** fila y **un** envío.
- Reintento: si el envío falla, la fila no queda, y la vuelta siguiente reintenta.
- El endpoint de tareas responde 404 sin secreto configurado, 401 con secreto equivocado.

## Variables de entorno nuevas

| Var | Propósito |
|---|---|
| `TASK_SECRET` | Protege `POST /tasks/due-date-reminders`. Sin ella el endpoint responde 404 |
| `DUE_DATE_REMINDERS_ENABLED` | Permite apagar el loop sin deploy si molesta |
