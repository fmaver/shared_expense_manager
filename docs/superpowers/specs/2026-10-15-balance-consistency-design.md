# Saldos consistentes: derivados al leer, mes bloqueado al escribir

## Incidente

2026-10-14, grupo Buzios (id 8). Marian veía −$100.189 adentro del grupo y −$87.316 en "Tu saldo
en grupos". Rehaciendo el saldo desde las filas de `expenses`, −$87.316 era el correcto: el JSON
`monthly_shares.balances` tenía el gasto 1525 ("Pollera y pareo", 40% = $12.872,80) aplicado dos
veces. Un recálculo posterior lo corrigió solo.

Causa estructural: el saldo de un mes vivía en dos lugares. Las pantallas del grupo leían el JSON
guardado, mantenido con un read-modify-write sin lock (incremental al crear, completo al editar o
borrar). El resumen personal lo recalculaba desde las filas. Un repro con dos altas concurrentes
pierde una de las dos en el JSON.

## Decisión

1. **Mes abierto: el saldo se deriva de sus filas en cada lectura.** El punto único es
   `SQLAlchemyExpenseRepository._to_domain_monthly_share`, por donde pasa toda lectura (pantalla
   del grupo, resumen, saldar, salir/archivar, eventos, WhatsApp, meses sin saldar). Usa los
   miembros del grupo (`GroupRepository.list_members`) y `usd_rate_for` (blue para USD). Si una
   fila ya no valida su split, se loguea y se usa el JSON guardado (mismo criterio que tenía el
   ledger). El JSON se copia: el dominio nunca más muta el dict del ORM.
2. **Mes saldado: el JSON es una foto congelada.** No se recalcula; con el blue de hoy movería un
   mes cerrado.
3. **Escrituras que deciden sobre el estado del mes toman `SELECT … FOR UPDATE` sobre la fila del
   mes y hacen un solo commit:**
   - alta (`_add_to_monthly_share`): get-or-create con `INSERT … ON CONFLICT DO NOTHING` + lock,
     chequea saldado, inserta, recalcula completo, commit. `repository.add` pasa a `flush`.
   - saldar: lock, recalcular, agregar los gastos de balanceo, marcar saldado, un commit. Un alta
     concurrente espera y después ve el mes saldado (rechazo), o entra antes y el saldo la incluye.
   - des-saldar: lock en el repositorio dentro de su único commit.
4. **Fuera de alcance (preexistente):** editar o borrar no bloquea el mes, y el backend no impide
   editar un mes saldado. Con lectura derivada no pueden corromper el saldo visible; quedan como
   deuda para otro cambio.

## Costo

Recalcular un mes en memoria: 0,15 ms con 40 gastos, 3,6 ms con 1.000 (10 miembros). Las filas ya
se cargaban en cada lectura y en cada alta; lo nuevo es una query de miembros por carga. El lock es
por grupo y mes: dos grupos distintos nunca se esperan.

## Tests

- Integración (Postgres): un JSON corrompido a mano no aparece en `GET /shares/{y}/{m}` ni en el
  ledger; un mes saldado conserva su foto; el lock bloquea a una segunda sesión hasta el commit;
  dos get-or-create concurrentes del mismo mes no fallan; un alta que espera a un saldar en curso
  es rechazada.
- Unit: un alta sobre un mes con JSON corrompido deja el saldo derivado.

## Plan

1. RED integración: JSON corrompido servido por `GET /shares` → derivar en
   `_to_domain_monthly_share` (+ copia del dict, + fallback). Quitar el recálculo duplicado del
   ledger.
2. RED unit: alta incremental sobre base corrupta → recálculo completo en `_add_to_monthly_share`.
3. RED integración: lock / get-or-create concurrente / alta vs saldar →
   `get_monthly_share_for_update` (default en el ABC para el mock), `add` con flush, saldar en un
   solo commit, des-saldar con lock.
4. Gates: `make lint`, unit, integración. Review. PR.
