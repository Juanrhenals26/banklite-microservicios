# BankLite — Identity, Account, Ledger y Transfer Service

Implementación de cuatro microservicios de la plataforma de banca digital **BankLite**,
construidos de forma autónoma, con persistencia propia por servicio y comunicación
**síncrona (REST)** y **asíncrona (eventos sobre RabbitMQ)** entre ellos.

## Alcance de esta entrega

Esta entrega implementa y prueba **4 de los 9 microservicios** que componen el diseño completo de
BankLite: `identity-service`, `account-service`, `ledger-service` y `transfer-service`. El resto
de los diagramas de este repositorio (autorización de tarjeta con detección de fraude, topología
de despliegue) documentan la **arquitectura objetivo de todo el sistema** — Card, Fraud,
Notification y Compliance todavía no tienen código en este repositorio.

El modelo de datos de los cuatro servicios esta alineado con el documento oficial del equipo (ER,
indices y restricciones): las tablas, columnas, llaves foraneas, indices e integridad (`CHECK`)
reproducen exactamente las entidades `USUARIO`, `DOCUMENTO_IDENTIDAD`, `VERIFICACION_KYC`,
`EVALUACION_RIESGO`, `CUENTA`, `LIMITE_OPERATIVO`, `RESTRICCION_REGULATORIA`, `TRANSACCION`,
`ASIENTO_CONTABLE`, `CUENTA_CONTABLE`, `TRANSFERENCIA`, `BENEFICIARIO`, `RIEL_PAGO` y
`TRANSFERENCIA_PROGRAMADA` definidas alli.

## Arquitectura

![Arquitectura de microservicios](banklite_arquitectura_microservicios.svg)

![Comunicación entre Identity y Account](banklite_identity_account_comunicacion.svg)

### Los cuatro microservicios

| Servicio | Puerto | Responsabilidad única | Base de datos |
|---|---|---|---|
| `identity-service` | 8001 | Registro de usuarios y verificación KYC contra un proveedor externo | `identity_db` (PostgreSQL) |
| `account-service` | 8002 | Apertura y administración de cuentas con límites regulatorios por país | `account_db` (PostgreSQL) |
| `ledger-service` | 8003 | Contabilidad por doble partida; fuente de verdad del saldo de cada cuenta | `ledger_db` (PostgreSQL) |
| `transfer-service` | 8004 | Transferencias internas y externas, con validación de fondos | `transfer_db` (PostgreSQL) |

Cada servicio tiene **su propia base de datos** y ninguno accede a las tablas del otro
(*database per service*). El único punto de contacto entre ellos son la API REST y el bus de eventos.

### Comunicación síncrona (REST)

```
account-service   ──── GET /users/{id} ─────────>  identity-service
transfer-service  ──── GET /accounts/{id} ───────>  account-service
transfer-service  ──── GET/POST /ledger/... ─────>  ledger-service
ledger-service     ──── GET /accounts/{id} ─────────>  account-service
```

Antes de abrir una cuenta, `account-service` consulta el estado real del usuario en
`identity-service`. Antes de mover dinero, `transfer-service` valida en tiempo real que la cuenta
origen exista y esté activa (`account-service`), consulta el saldo real y registra la partida
doble (`ledger-service`) — esta última es la operación crítica que el documento exige hacer por
REST, no por evento. `ledger-service`, a su vez, valida contra `account-service` la primera vez
que ve una cuenta, antes de crear su proyección contable. Si cualquiera de estas llamadas no
responde, el servicio que la hizo devuelve `503` en vez de continuar con información no verificada.

### Comunicación asíncrona (eventos)

```
identity-service ──publish identity.verified──> [banklite.events] ──┐
transfer-service ──publish transfer.completed──> [banklite.events] ──┼──> [account.events] ──> account-service
```

Cuando el proveedor KYC aprueba a un usuario, `identity-service` publica `identity.verified`.
Cuando una transferencia se completa, `transfer-service` publica `transfer.completed`.
`account-service` consume **ambos** desde la misma cola (`account.events`) y alimenta dos
proyecciones locales (`usuario_verificado` y `transferencia_recibida`), sin bloquear a quien
publicó el evento. Ninguna de las dos tablas forma parte del modelo entidad-relación oficial: son
tablas propias de la implementación, necesarias para demostrar la comunicación asíncrona.

Configuración exigida por el dominio financiero: exchange y cola **durables**, mensajes
**persistentes** (`delivery_mode=2`) y **confirmaciones de entrega explícitas**
(*publisher confirms*) para no perder eventos.

Puedes ver la evidencia del consumo con `GET /verified-users` y `GET /transfers-received` en el
puerto 8002: esas tablas **solo** se llenan a través de los eventos.

## Panel web

`services/web-panel` es una interfaz sencilla en **Next.js 14 + TypeScript + Tailwind CSS**
que consume `identity-service` y `account-service` desde el navegador: registrar usuario, enviar
el KYC, listar usuarios, abrir cuenta, cambiar su estado, y ver en vivo la proyección
`usuario_verificado` que alimenta el evento asíncrono. No añade lógica de negocio nueva — es solo
la capa visual. **Pendiente:** todavía no tiene pantallas para `ledger-service` ni
`transfer-service` — por ahora esos dos se prueban por Swagger (`/docs`).

Como las variables `NEXT_PUBLIC_*` quedan incrustadas en el JavaScript del navegador en el
momento de compilar la imagen, apuntan a `http://localhost:8001` y `http://localhost:8002`
(los puertos publicados en tu máquina), no a los nombres internos de los contenedores — el
navegador corre fuera de la red de Docker.

## Cómo ejecutarlo en local

Requisitos: Docker Desktop. Si además quieres correr el panel web fuera de Docker (ver la nota
al final de esta sección), necesitas Node.js instalado en Windows.

```bash
docker compose up --build
```

Eso levanta diez contenedores: cuatro PostgreSQL (uno por servicio), RabbitMQ, los cuatro
microservicios y el panel web.

| Recurso | URL |
|---|---|
| Panel web | http://localhost:3000 |
| Identity Service (Swagger) | http://localhost:8001/docs |
| Account Service (Swagger) | http://localhost:8002/docs |
| Ledger Service (Swagger) | http://localhost:8003/docs |
| Transfer Service (Swagger) | http://localhost:8004/docs |
| Panel de RabbitMQ | http://localhost:15672 (usuario `banklite`, clave `banklite`) |

Para detener todo:

```bash
docker compose down          # conserva los datos
docker compose down -v       # borra también las bases de datos
```

### Nota: si `docker compose up --build web-panel` falla con `SIGBUS`

En algunas instalaciones de Docker Desktop en Windows, el proceso que compila el panel dentro
del contenedor se cae con `Next.js build worker exited with code: null and signal: SIGBUS`. Es un
problema del entorno de Docker (no del código) y la salida es correr el panel directo en Windows,
fuera de Docker, mientras los microservicios y las bases de datos sí quedan en Docker:

```powershell
# Terminal 1: solo el backend (sin el panel)
docker compose up --build identity-db account-db ledger-db transfer-db rabbitmq identity-service account-service ledger-service transfer-service

# Terminal 2: el panel, nativo en Windows
cd services\web-panel
npm install
npm run dev
```

El panel toma `http://localhost:8001` y `http://localhost:8002` por defecto (los mismos puertos
publicados por Docker), así que no necesita configuración adicional. Entra a `http://localhost:3000`.

### Prueba de humo automática

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1
```

Recorre todos los endpoints, valida los códigos HTTP y comprueba que el evento asíncrono llegó.

## Endpoints

### Identity Service — `http://localhost:8001`

#### `POST /users` — registrar usuario (tabla `usuario`)

```json
// Petición
{ "nombre": "Juan", "apellido": "Rhenals", "email": "juan@example.com", "telefono": "+573001234567", "pais_residencia": "CO" }
```

```json
// Respuesta 201
{
  "id_usuario": "31b0e5f5-4b50-4b80-aa49-ccc197344776",
  "nombre": "Juan",
  "apellido": "Rhenals",
  "email": "juan@example.com",
  "telefono": "+573001234567",
  "pais_residencia": "CO",
  "estado": "pendiente_verificacion",
  "fecha_registro": "2026-09-15T22:23:23.043816Z"
}
```

Errores: `409` si el email ya existe, `422` si los datos no pasan validación.

#### `GET /users/{id}` — consultar usuario

Este es el endpoint que `account-service` llama de forma **síncrona**. Devuelve `200` o `404`.

#### `GET /users?estado=&limit=&offset=` — listar usuarios

Devuelve `200` con la lista paginada. El filtro `estado` es opcional.

#### `POST /kyc/verify` — verificar identidad

Registra (o reutiliza) el `documento_identidad` del usuario, crea la `verificacion_kyc` con su
resultado y la `evaluacion_riesgo` asociada. Si el resultado es aprobado, actualiza el estado del
usuario y publica el evento asíncrono.

```json
// Petición
{
  "id_usuario": "31b0e5f5-4b50-4b80-aa49-ccc197344776",
  "tipo_documento": "cedula",
  "numero_documento": "1098765432",
  "pais_emision": "CO",
  "fecha_expiracion": "2030-01-01"
}
```

```json
// Respuesta 200
{
  "verificacion": {
    "id_verificacion": "e520859c-a68f-459e-b15f-d744f5694b6b",
    "id_usuario": "31b0e5f5-4b50-4b80-aa49-ccc197344776",
    "proveedor_externo": "KYC-4A2C44B6B143",
    "resultado": "aprobado",
    "fecha_verificacion": "2026-09-15T22:23:23.043816Z",
    "evaluaciones": [
      { "id_evaluacion": "9b7c...", "nivel_riesgo": "bajo", "score": "18.00", "fecha_evaluacion": "2026-09-15T22:23:23.043816Z" }
    ]
  },
  "estado_usuario": "verificado",
  "event_published": true,
  "event_name": "identity.verified"
}
```

Errores: `404` si el usuario no existe, `409` si ya estaba verificado o si el `numero_documento` es
de otro usuario, `422` si el documento es inválido.

> El proveedor KYC está simulado de forma determinista: cualquier `numero_documento` que termine en
> `0000` se rechaza (y su evaluación de riesgo queda en `alto`), el resto se aprueba con un
> `nivel_riesgo` derivado de un hash del documento. Así se pueden demostrar los distintos caminos
> sin depender de un tercero real.

#### `GET /kyc/{user_id}` — historial de verificaciones

Devuelve `200` con la lista de `verificacion_kyc` (cada una con su `evaluacion_riesgo` anidada), o
`404` si el usuario no existe.

### Account Service — `http://localhost:8002`

#### `POST /accounts` — abrir cuenta (tablas `cuenta`, `limite_operativo` x2, `restriccion_regulatoria`)

```json
// Petición
{ "id_usuario": "31b0e5f5-4b50-4b80-aa49-ccc197344776" }
```

```json
// Respuesta 201
{
  "cuenta": {
    "id_cuenta": "cb862923-14e6-4d15-868a-1db7766eed5b",
    "id_usuario": "31b0e5f5-4b50-4b80-aa49-ccc197344776",
    "tipo_cuenta": "ahorros",
    "moneda": "COP",
    "estado": "activa",
    "fecha_apertura": "2026-09-15T22:23:23.397526Z",
    "fecha_cierre": null
  },
  "limites": [
    { "id_limite": "...", "tipo_limite": "diario", "monto_maximo": "5000000.00", "periodo": "dia" },
    { "id_limite": "...", "tipo_limite": "mensual", "monto_maximo": "50000000.00", "periodo": "mes" }
  ],
  "restriccion": { "id_restriccion": "...", "pais": "CO", "descripcion": "Limites regulatorios estandar de CO para cuentas en COP", "fecha_aplicacion": "2026-09-15" },
  "validado_via": "identity-service (REST sincrono)",
  "evento_proyeccion_encontrada": true
}
```

Errores: `404` si el usuario no existe en Identity, `409` si no pasó el KYC o si ya tiene cuenta en
esa moneda, `400` si el país no está habilitado o la moneda no corresponde, `503` si Identity no responde.

#### `GET /accounts?id_usuario=` — listar cuentas

#### `GET /accounts/{id}` — consultar una cuenta (`200` / `404`)

#### `GET /accounts/{id}/limits` — límites operativos de la cuenta (tabla `limite_operativo`)

#### `PATCH /accounts/{id}/status` — cambiar estado

```json
// Petición
{ "estado": "suspendida" }
```

Valores permitidos: `activa`, `suspendida`, `cerrada`. Una cuenta `cerrada` no puede volver a cambiar de estado (`409`).

#### `GET /verified-users` — evidencia de la comunicación asíncrona (identity.verified)

Muestra la proyección local `usuario_verificado`, alimentada exclusivamente por el evento `identity.verified`.

#### `GET /transfers-received` — evidencia de la comunicación asíncrona (transfer.completed)

Muestra la proyección local `transferencia_recibida`, alimentada exclusivamente por el evento
`transfer.completed` que publica `transfer-service`.

### Ledger Service — `http://localhost:8003`

#### `POST /ledger/entries` — registrar una transacción con su partida doble (tablas `transaccion`, `asiento_contable`, `cuenta_contable`)

```json
// Petición
{
  "tipo_transaccion": "transferencia",
  "referencia": "a1b2c3d4-...",
  "movimientos": [
    { "id_cuenta": "cb862923-...", "tipo_movimiento": "debito", "monto": "20000" },
    { "id_cuenta": "8f21a0e1-...", "tipo_movimiento": "credito", "monto": "20000" }
  ]
}
```

```json
// Respuesta 201
{
  "id_transaccion": "e1f2...",
  "tipo_transaccion": "transferencia",
  "referencia": "a1b2c3d4-...",
  "fecha_hora": "2026-09-19T10:00:00Z",
  "estado": "registrada",
  "asientos": [
    { "id_asiento": "...", "id_transaccion": "e1f2...", "id_cuenta_contable": "...", "tipo_movimiento": "debito", "monto": "20000.00", "fecha_registro": "..." },
    { "id_asiento": "...", "id_transaccion": "e1f2...", "id_cuenta_contable": "...", "tipo_movimiento": "credito", "monto": "20000.00", "fecha_registro": "..." }
  ]
}
```

Cada movimiento trae un `id_cuenta` (la cuenta de `account-service`, no el `id_cuenta_contable`
interno). La primera vez que el ledger ve una cuenta, la valida **sincronamente** contra
`account-service` (existe y está `activa`) antes de crear su `cuenta_contable`. Convención de
signo: `credito` aumenta el saldo del titular, `debito` lo disminuye.

Errores: `409` si la `referencia` ya existe o si la partida no balancea (`422`, ver abajo), `404`
si alguna cuenta no existe en `account-service`, `409` si alguna cuenta no está activa, `503` si
`account-service` no responde.

> Validación de partida doble: la suma de los movimientos `debito` debe ser igual a la suma de
> los `credito` del mismo envío, o la petición se rechaza con `422` antes de tocar la base de datos.

#### `GET /ledger/accounts/{id_cuenta}` — saldo actual de una cuenta (tabla `cuenta_contable`)

Devuelve `200` con `saldo_actual`, o `404` si la cuenta nunca tuvo movimientos.

#### `GET /ledger/transactions/{id_transaccion}` — detalle de una transacción con sus asientos

### Transfer Service — `http://localhost:8004`

#### `POST /beneficiaries` / `GET /beneficiaries?id_usuario=` — catálogo de beneficiarios (tabla `beneficiario`)

#### `POST /payment-rails` / `GET /payment-rails` — catálogo de rieles de pago (tabla `riel_pago`: `ACH`, `SWIFT`, `interno`)

#### `POST /transfers` — ejecutar una transferencia (tabla `transferencia`)

```json
// Petición
{ "id_cuenta_origen": "cb862923-...", "id_beneficiario": "1a2b...", "id_riel": "3c4d...", "monto": "20000" }
```

```json
// Respuesta 201
{
  "transferencia": { "id_transferencia": "...", "id_cuenta_origen": "...", "id_beneficiario": "...", "id_riel": "...", "monto": "20000.00", "estado": "completada", "fecha_solicitud": "..." },
  "id_transaccion_ledger": "e1f2...",
  "validado_via": "account-service + ledger-service (REST sincrono)",
  "event_published": true
}
```

Flujo interno: (1) valida beneficiario y riel en su propia base, (2) valida la cuenta origen
**sincronamente** contra `account-service`, (3) valida fondos suficientes **sincronamente**
contra `ledger-service`, (4) registra la partida doble en `ledger-service` (también síncrono),
(5) si todo salió bien, publica **asincronamente** el evento `transfer.completed`. Si el riel es
`interno`, el `cuenta_destino` del beneficiario debe ser el `id_cuenta` (UUID) de la cuenta
destino dentro de BankLite; si el riel es `ACH`/`SWIFT` (externo), el dinero se acredita
contablemente a una cuenta puente de compensación (`00000000-0000-0000-0000-000000000001`), ya
que el beneficiario no tiene cuenta dentro de BankLite — es la simplificación de una cuenta
nostro real.

Errores: `404` si el beneficiario, el riel o la cuenta origen no existen; `409` si el riel está
inactivo, la cuenta origen no está activa o los fondos son insuficientes; `400` si el riel es
`interno` y `cuenta_destino` no es un UUID válido; `502` si `ledger-service` rechaza la operación
ya vencidas las validaciones previas; `503` si `account-service` o `ledger-service` no responden.

#### `GET /transfers?id_cuenta_origen=` / `GET /transfers/{id}` — listar y consultar transferencias

#### `POST /transfers/{id}/schedule` / `GET /transfers/{id}/schedule` — recurrencia (tabla `transferencia_programada`)

Modela los datos de una transferencia recurrente (`frecuencia`, `proxima_ejecucion`). La
ejecución automática periódica (el disparador que la repita en cada fecha) queda como trabajo
futuro — se documenta la limitación en vez de simularla.

## Límites regulatorios por país

`account-service` asigna los límites según el país del usuario, tal como exige el diseño de BankLite:

| País | Moneda | Límite diario | Límite mensual |
|---|---|---|---|
| CO | COP | 5.000.000 | 50.000.000 |
| MX | MXN | 20.000 | 200.000 |
| US | USD | 2.500 | 25.000 |
| ES | EUR | 2.000 | 20.000 |
| PE | PEN | 8.000 | 80.000 |

Un país fuera de esta tabla produce `400`.

## Modelo de datos

Este es el modelo normalizado (3FN) definido en el documento oficial del proyecto — coincide tabla
por tabla, columna por columna, con el diagrama entidad-relación de `identity-service` y
`account-service`. Puedes verificarlo tú mismo entrando a cada base con `psql` (ver más abajo) y
corriendo `\dt` (lista de tablas) y `\d <tabla>` (columnas, índices y restricciones de una tabla).

**identity_db**

| Tabla | Columnas | Relación |
|---|---|---|
| `usuario` | `id_usuario` PK, `nombre`, `apellido`, `email` (único), `telefono`, `pais_residencia`, `fecha_registro`, `estado` | raíz |
| `documento_identidad` | `id_documento` PK, `id_usuario` FK, `tipo_documento`, `numero_documento` (único), `pais_emision`, `fecha_expiracion` | Usuario 1:N |
| `verificacion_kyc` | `id_verificacion` PK, `id_usuario` FK, `proveedor_externo`, `resultado`, `fecha_verificacion` | Usuario 1:N |
| `evaluacion_riesgo` | `id_evaluacion` PK, `id_verificacion` FK, `nivel_riesgo`, `score`, `fecha_evaluacion` | Verificacion_KYC 1:N |

Índices: `idx_usuario_email`, `idx_documento_usuario`, `idx_verificacion_usuario`,
`idx_evaluacion_verificacion`. Restricciones `CHECK`: `tipo_documento` en
`(cedula, pasaporte, licencia)`, `resultado` en `(pendiente, aprobado, rechazado)`, `nivel_riesgo`
en `(bajo, medio, alto)`.

**account_db**

| Tabla | Columnas | Relación |
|---|---|---|
| `cuenta` | `id_cuenta` PK, `id_usuario` FK externa (a identity-service, sin FK real), `tipo_cuenta`, `moneda`, `estado`, `fecha_apertura`, `fecha_cierre` | raíz |
| `limite_operativo` | `id_limite` PK, `id_cuenta` FK, `tipo_limite`, `monto_maximo`, `periodo` | Cuenta 1:N |
| `restriccion_regulatoria` | `id_restriccion` PK, `id_cuenta` FK, `pais`, `descripcion`, `fecha_aplicacion` | Cuenta 1:N |
| `usuario_verificado` | `id_usuario` PK, `email`, `pais_residencia`, `verificado_en`, `recibido_en` | proyección asíncrona (no forma parte del ER oficial) |

Índices: `idx_cuenta_usuario`, `idx_limite_cuenta`, `idx_restriccion_cuenta`. Restricciones
`CHECK`: `estado` de `cuenta` en `(activa, suspendida, cerrada)`, `monto_maximo` ≥ 0. Restricción
única sobre `(id_usuario, moneda)` en `cuenta`. Ademas, `usuario_verificado` y
`transferencia_recibida` (proyecciones asincronas, no forman parte del ER oficial).

**ledger_db**

| Tabla | Columnas | Relación |
|---|---|---|
| `transaccion` | `id_transaccion` PK, `tipo_transaccion`, `referencia` (único), `fecha_hora`, `estado` | raíz |
| `asiento_contable` | `id_asiento` PK, `id_transaccion` FK, `id_cuenta_contable` FK, `tipo_movimiento`, `monto`, `fecha_registro` | Transaccion 1:N, append-only |
| `cuenta_contable` | `id_cuenta_contable` PK, `id_cuenta` FK externa (a account-service, único), `saldo_actual`, `moneda`, `fecha_actualizacion` | fuente de verdad del saldo |

Índices: `idx_asiento_transaccion`, `idx_asiento_cuenta_contable`, `idx_transaccion_referencia`.
Restricciones `CHECK`: `tipo_movimiento` en `(debito, credito)`, `monto > 0`. Regla de negocio
(doble partida): la suma de débitos debe ser igual a la suma de créditos de cada transacción.

**transfer_db**

| Tabla | Columnas | Relación |
|---|---|---|
| `transferencia` | `id_transferencia` PK, `id_cuenta_origen` FK externa, `id_beneficiario` FK, `id_riel` FK, `monto`, `estado`, `fecha_solicitud` | raíz |
| `beneficiario` | `id_beneficiario` PK, `id_usuario` FK externa, `nombre`, `cuenta_destino`, `banco_destino` | reutilizable entre transferencias |
| `riel_pago` | `id_riel` PK, `tipo`, `pais`, `activo` | reutilizable entre transferencias |
| `transferencia_programada` | `id_programacion` PK, `id_transferencia` FK (único), `frecuencia`, `proxima_ejecucion` | Transferencia 1:1 |

Índices: `idx_transferencia_beneficiario`, `idx_transferencia_riel`, `idx_transferencia_estado`,
`idx_programada_transferencia`. Restricciones `CHECK`: `monto > 0`, `estado` en `(pendiente,
completada, rechazada)`, `tipo` de `riel_pago` en `(ACH, SWIFT, interno)`.

### Cómo verificar las bases de datos con `psql`

```powershell
docker ps --format "{{.Names}}"                              # confirma los nombres exactos
docker exec -it banklite-identity-db psql -U banklite -l      # lista las bases (debe verse identity_db)
docker exec -it banklite-identity-db psql -U banklite -d identity_db
```

Dentro de `psql`:

```
\dt                     -- lista las tablas de la base
\d usuario               -- columnas, tipos, PK, índices y CHECK de esa tabla
select * from usuario;   -- ver los datos
\q                       -- salir
```

Lo mismo aplica a `account_db`, `ledger_db` y `transfer_db`: `docker exec -it banklite-account-db
psql -U banklite -d account_db`, `docker exec -it banklite-ledger-db psql -U banklite -d
ledger_db`, `docker exec -it banklite-transfer-db psql -U banklite -d transfer_db`.

## Manejo de errores

| Código | Cuándo se devuelve |
|---|---|
| `200` | Consulta o actualización exitosa |
| `201` | Recurso creado |
| `400` | Regla de negocio incumplida (país no habilitado, moneda incorrecta) |
| `404` | El recurso no existe |
| `409` | Conflicto de estado (email duplicado, cuenta duplicada, KYC pendiente o repetido) |
| `422` | Validación de entrada fallida (incluye partida doble desbalanceada) |
| `502` | Una dependencia síncrona respondió pero rechazó la operación |
| `503` | Una dependencia síncrona no está disponible |
| `500` | Error no controlado, capturado por un manejador global |

## Tecnologías

- **Python 3.12** con **FastAPI** — documentación OpenAPI automática en `/docs`
- **SQLAlchemy 2.0** como ORM y **PostgreSQL 16** como motor
- **Pydantic v2** para validación de entrada y serialización
- **RabbitMQ 3.13** para la mensajería asíncrona, con **pika**
- **httpx** para la comunicación síncrona entre servicios
- **Next.js 14 + TypeScript + Tailwind CSS** para el panel web
- **Docker Compose** para levantar todo el entorno local

## Estructura del proyecto

```
.
├── docker-compose.yml
├── README.md
├── scripts/
│   └── smoke_test.ps1
└── services/
    ├── identity-service/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── app/
    │       ├── main.py          # arranque de FastAPI y manejadores de error
    │       ├── config.py        # configuración por variables de entorno
    │       ├── database.py      # motor y sesión de SQLAlchemy
    │       ├── models.py        # usuario, documento_identidad, verificacion_kyc, evaluacion_riesgo
    │       ├── schemas.py       # validación de entrada y salida
    │       ├── kyc_provider.py  # proveedor KYC externo simulado + evaluación de riesgo
    │       ├── events.py        # publicación de identity.verified
    │       └── routers/
    │           ├── users.py     # POST/GET /users
    │           └── kyc.py       # POST /kyc/verify, GET /kyc/{user_id}
    ├── account-service/
        ├── Dockerfile
        ├── requirements.txt
        └── app/
            ├── main.py
            ├── config.py
            ├── database.py
            ├── models.py           # cuenta, limite_operativo, restriccion_regulatoria,
            │                       # usuario_verificado, transferencia_recibida
            ├── schemas.py
            ├── limits.py           # límites regulatorios por país
            ├── identity_client.py  # cliente REST síncrono hacia identity-service
            ├── consumer.py         # consumidor de RabbitMQ (identity.verified + transfer.completed)
            └── routers/
                └── accounts.py
    ├── ledger-service/
        ├── Dockerfile
        ├── requirements.txt
        └── app/
            ├── main.py
            ├── config.py
            ├── database.py
            ├── models.py           # transaccion, asiento_contable, cuenta_contable
            ├── schemas.py
            ├── account_client.py   # cliente REST síncrono hacia account-service
            └── routers/
                └── ledger.py       # POST /ledger/entries, GET /ledger/accounts|transactions
    ├── transfer-service/
        ├── Dockerfile
        ├── requirements.txt
        └── app/
            ├── main.py
            ├── config.py
            ├── database.py
            ├── models.py           # transferencia, beneficiario, riel_pago, transferencia_programada
            ├── schemas.py
            ├── account_client.py   # cliente REST síncrono hacia account-service
            ├── ledger_client.py    # cliente REST síncrono hacia ledger-service
            ├── events.py           # publicación de transfer.completed
            └── routers/
                ├── catalog.py      # beneficiarios y rieles de pago
                └── transfers.py    # POST /transfers, schedule, listado
    └── web-panel/
        ├── Dockerfile
        ├── package.json
        ├── app/
        │   ├── layout.tsx
        │   ├── page.tsx      # las tres pantallas: usuarios, KYC, cuentas
        │   └── globals.css
        ├── components/       # tarjetas y banners reutilizables
        └── lib/
            └── api.ts        # cliente HTTP hacia los dos microservicios
```
