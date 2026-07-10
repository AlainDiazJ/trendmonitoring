# Trend Monitoring — Celda de Pruebas de Motores (piloto LEAP)

Dashboard en Streamlit para monitorear tendencias de parametros de motores
LEAP-1A / LEAP-1B a partir de reportes de celda de pruebas (Excel), con
deteccion de anomalias (umbrales, CUSUM, rachas), correlacion contra la
celda de pruebas (+/-N sigma) y bandas de baseline historico.

## Arquitectura

```
app.py                     router: carga datos, filtros del sidebar, despacha la pestana activa
views/                     una vista por pestana (Tendencia, Correlacion, Correlacion Ref.,
                            Anomalias, Modificadores, Eventos, Datos) + sidebar.py
services/                  data_loader (carga/normaliza motores.db), deletion_service
                            (retiro + cuarentena de Exceles), unit_corrections
etl.py                     ingesta de Exceles de prueba -> motores.db (idempotente)
resync_measurements.py     agrega mediciones nuevas a puntos ya ingeridos (tras editar mapping.yaml)
db_migrations.py           migracion de schema + backfill de motores.db
config_store.py            configuracion de usuario (config.db): vistas, umbrales, eventos,
                            puntos ocultos, baselines aprobados
report_export.py           exportacion de reportes (PDF/PNG via matplotlib + reportlab)
mapping.yaml                diccionario de nombres crudos -> canonicos del Buffer de cada Excel
```

Los datos de los motores viven en `data/motores.db` (SQLite, generado por el
ETL). La configuracion del usuario vive en `config.db` (SQLite, se crea
solo). Ninguno de los dos se versiona en git.

## Requisitos

Python 3.11+ recomendado.

```
pip install -r requirements.txt
```

## Estructura de carpetas recomendada + boton Sync

La app espera que `Unloaded/` y `Loaded/` vivan como hermanas de la carpeta
del proyecto (donde esta `app.py`), sin importar desde donde se lance
`streamlit run`:

```
trend monitoring/
├── App/            (este repo: app.py, data/motores.db, config.db, ...)
├── Loaded/         (Exceles ya cargados, ordenados por variante)
│   ├── LEAP-1A/
│   ├── LEAP-1B/
│   ├── CFM56-5A/
│   └── CFM56-7B/
└── Unloaded/       (Exceles nuevos, una sola carpeta plana)
```

Flujo normal de operacion:

1. Coloca los Exceles nuevos en `trend monitoring/Unloaded/`.
2. Abre la app: `cd .../App` y `streamlit run app.py`.
3. Pulsa **Sync** (esquina superior derecha).
4. Los Exceles que cargan bien se mueven automaticamente a
   `Loaded/<variante>/`.
5. Los duplicados o los que fallan (p. ej. sin hoja `Buffer`) se quedan en
   `Unloaded/`; el resumen del Sync explica por que.

Si `Unloaded/` no existe, el boton Sync avisa y no hace nada — crearla es
suficiente para habilitarlo.

## Flujo de uso (linea de comandos, alternativo al boton Sync)

1. **Cargar datos** — corre el ETL sobre las carpetas con los Exceles de
   prueba (`.xls`, `.xlsx`, `.xlsm`, hoja `Buffer`):

   ```
   python etl.py "/ruta/a/pruebas_leap_1A" --db data/motores.db --mapping mapping.yaml
   python etl.py "/ruta/a/pruebas_leap_1B" --db data/motores.db --mapping mapping.yaml
   ```

   Es idempotente: puedes correrlo varias veces y sobre varias carpetas sin
   duplicar (usa un hash por archivo).

   Si editas `mapping.yaml` para agregar canonicos nuevos, los puntos que ya
   estaban en la base NO los reciben automaticamente (el archivo entero se
   salta por idempotencia). Para eso corre (busca los Exceles de forma
   recursiva, asi que puedes pasar `Loaded/` directamente aunque tenga
   subcarpetas por variante):

   ```
   python resync_measurements.py --db data/motores.db --mapping mapping.yaml \
       --folder "/ruta/a/pruebas_leap_1A" --folder "/ruta/a/pruebas_leap_1B"
   ```

2. **Verificar** (opcional) — resumen legible de lo que entro a la base:

   ```
   python verificar.py --db data/motores.db
   ```

3. **Levantar el dashboard**:

   ```
   streamlit run app.py
   ```

   Abre `http://localhost:8501`.

## Correlacion vs celda de pruebas

La pestana "Correlacion Ref." compara los puntos historicos del motor contra
la curva de correlacion de la celda de pruebas. Espera un Excel
(`Datos Correlacion.xlsx` junto a `app.py`, o subido desde la UI) con una
hoja por variante (`LEAP-1A`, `LEAP-1B`) y 6 bloques de columnas de datos.
El formato exacto esta documentado en el docstring de
`views/correlacion_ref.py`.

## Correccion de unidades (kg/h -> lb/h)

Algunos reportes de flujo de combustible capturaron el numero en kg/h aunque
la unidad guardada ya dice `pph` (la etiqueta es correcta, el dato esta mal).
Las reglas de correccion (variante + parametro + ventana de fechas) viven en
`services/unit_corrections.py`. Cada vista que puede mostrar un parametro
afectado (Tendencia, Correlacion, Correlacion Ref.) muestra su propio
checkbox "Aplicar correccion kg/h -> lb/h" cuando corresponde; esta
desactivado por defecto para no alterar el dato crudo sin que el usuario lo
note.

## Tests

```
pip install pytest
pytest
```

Cubre principalmente la logica de `services/unit_corrections.py` y
`config_store.py` (sin dependencias de Streamlit).
