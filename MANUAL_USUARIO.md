# Manual de Usuario — Trend Monitoring (Celda de Pruebas de Motores LEAP)

Dashboard en Streamlit para monitorear tendencias de parámetros de motores
LEAP-1A / LEAP-1B (y CFM56-7B para la corrección de unidades) a partir de
reportes de celda de pruebas en Excel.

---

## 1. Qué hace la aplicación

- Carga los datos de pruebas (ya ingeridos por el ETL en `data/motores.db`).
- Permite explorar tendencias históricas de cualquier parámetro, con bandas
  de control, líneas de regresión y detección de deriva (CUSUM, rachas).
- Compara parámetros entre sí (correlación) y contra la curva de referencia
  de la celda de pruebas.
- Consolida anomalías (outliers, cruces de umbral, deriva, rachas) en una
  sola vista con seguimiento de estado (Pendiente / Revisada / Descartada).
- Vigila que los "modificadores" de celda (factores de corrección) se
  mantengan constantes por rating, para detectar recalibraciones.
- Permite marcar eventos (actualizaciones, recalibraciones) que se dibujan
  en las gráficas.
- Permite retirar puntos de datos erróneos con cuarentena del Excel de
  origen (trazable, reversible).
- Exporta reportes en Excel y PDF.

---

## 2. Requisitos e instalación

Python 3.11+ recomendado.

```
pip install -r requirements.txt
```

## 3. Flujo de uso

### 3.1 Cargar datos (ETL)

Antes de usar el dashboard hay que ingerir los Excel de prueba (`.xls`,
`.xlsx`, `.xlsm`, hoja `Buffer`) a la base SQLite `data/motores.db`:

```
python etl.py "/ruta/a/pruebas_leap_1A" --db data/motores.db --mapping mapping.yaml
python etl.py "/ruta/a/pruebas_leap_1B" --db data/motores.db --mapping mapping.yaml
```

Es **idempotente**: se puede correr varias veces y sobre varias carpetas sin
duplicar datos (usa un hash por archivo).

Si se edita `mapping.yaml` para agregar parámetros canónicos nuevos, los
puntos que ya estaban en la base **no** los reciben automáticamente (el
archivo entero se salta por idempotencia). Para eso hay que correr:

```
python resync_measurements.py --db data/motores.db --mapping mapping.yaml \
    --folder "/ruta/a/pruebas_leap_1A" --folder "/ruta/a/pruebas_leap_1B"
```

### 3.2 Verificar (opcional)

Resumen legible de lo que entró a la base:

```
python verificar.py --db data/motores.db
```

### 3.3 Levantar el dashboard

```
streamlit run app.py
```

Se abre en `http://localhost:8501`.

Al iniciar, la app:
- Avisa si no encuentra `data/motores.db` (hay que correr el ETL primero).
- Avisa si hay puntos con fecha sin parsear o faltante (revisar la pestaña
  **Datos**).
- Excluye automáticamente los puntos marcados como **ocultos globalmente**
  (ver sección 4.5).

---

## 4. Barra lateral (filtros, siempre visibles)

### 4.1 Vistas favoritas
Expander en la parte superior. Permite:
- **Aplicar** una vista guardada previamente (restaura variante, parámetro,
  Description y rango de fechas).
- **Borrar** una vista guardada.
- **Guardar la vista actual** con un nombre (el guardado ocurre al final de
  cualquier acción, ya con todos los filtros aplicados).

### 4.2 Variante de motor
Selector único (radio) entre las variantes disponibles (p. ej. `LEAP-1A`,
`LEAP-1B`). Nunca hay dos variantes activas a la vez.

### 4.3 Rating / Punto (Description)
Multiselección de los "Description" (rating/punto de prueba) disponibles
para la variante activa. Por defecto vienen todos seleccionados. El número
entre paréntesis junto a cada opción indica cuántos puntos hay cargados
para el parámetro actualmente seleccionado en Tendencia.

> Varias funciones (bandas, umbrales fijos, baseline aprobado) requieren
> filtrar a **un solo** Description para tener sentido estadístico.

### 4.4 Rango de fechas
Expander plegable. Por defecto cubre todo el histórico de la variante
activa. Se puede acotar a un rango específico.

### 4.5 Puntos ocultos globales
Si hay puntos marcados como ocultos con alcance "Global" (se administran
desde **Correlación Ref.**), la app los excluye de **todas** las pestañas y
muestra un aviso. Si todos los puntos visibles quedan ocultos, se ofrece un
botón para restaurarlos.

---

## 5. Pestañas

La navegación entre pestañas es una barra horizontal debajo de los filtros:
**Tendencia · Correlación · Correlación Ref. · Anomalías · Modificadores ·
Eventos · Datos**.

### 5.1 Tendencia

Vista principal. Grafica un parámetro (eje X = número de reporte /
consecutivo, eje Y = valor) a lo largo del histórico filtrado.

**Modo comparación**: casilla para comparar hasta 4 parámetros a la vez,
cada uno con su propio eje Y (o normalizados a 0–100% en un solo eje).

En modo de un solo parámetro, la barra lateral despliega expanders
adicionales:

- **Bandas / baseline**
  - Casilla "Mostrar bandas (±N sigma)" y slider de N (1 a 6).
  - Selector de **baseline estadístico** (de dónde salen media y sigma):
    - *Histórico completo*: toda la historia de ese parámetro+Description.
    - *Visible*: solo lo que está filtrado/visible en pantalla.
    - *Rango manual*: un rango de fechas elegido aparte del filtro principal.
    - *Baseline aprobado*: usa media/sigma **congeladas** de un perfil
      guardado (ver más abajo). No se recalculan aunque cambien los filtros.
  - Requiere un solo Description activo.

- **Guardar baseline aprobado**: congela la media/sigma calculadas con la
  selección actual como un perfil con nombre, autor ("Aprobado por") y
  comentario. Útil para fijar un período estable de referencia (p. ej.
  antes de una recalibración) y que las bandas no se muevan después aunque
  entren datos nuevos.

- **Umbrales fijos (límites)**: límites manuales (inferior/superior) por
  variante + parámetro + Description, independientes de la estadística.
  Se guardan en `config.db` y se pueden reutilizar entre sesiones. Marca en
  rojo/tabla los puntos que los cruzan.

- **Tendencia / regresión**: línea de regresión lineal sobre los puntos
  visibles, con opción de proyectar N reportes hacia adelante para
  anticipar deriva.

- **Detección de drift**:
  - Media móvil (ventana configurable) dibujada sobre la gráfica.
  - **CUSUM** (suma acumulada de desviaciones normalizadas), con parámetros
    *k* (holgura) y *H* (límite de alarma), en una gráfica aparte debajo.
    Alerta si detecta deriva sostenida al alza o a la baja.
  - **Alerta de racha**: avisa si el parámetro lleva 4+ reportes
    consecutivos subiendo o bajando.

- **Eventos en la gráfica**: casilla para dibujar las marcas temporales
  creadas en la pestaña Eventos, como líneas verticales.

- **Corrección de unidades (kg/h → lb/h)**: cuando el parámetro
  seleccionado tiene una regla de corrección activa (ver sección 6),
  aparece una casilla "Aplicar corrección kg/h → lb/h", desactivada por
  defecto.

- **Exportar reporte**: al fondo de la pestaña, botones para descargar el
  reporte actual (datos + estadísticas + gráfica) en **Excel** o **PDF**,
  con toda la configuración de filtros/bandas/umbrales usada.

### 5.2 Correlación

Gráfica de dispersión (scatter) entre dos parámetros cualesquiera de la
variante activa (ej. empuje vs. flujo de combustible), elegidos en los
selectores "Eje X" y "Eje Y". Cada punto es un punto de prueba. Aplica la
misma corrección de unidades cuando corresponde.

### 5.3 Correlación Ref.

Compara los puntos históricos reales del motor contra la **curva de
correlación de referencia** de la celda de pruebas (6 pares fijos: N1R vs
N2R, N1R vs FNR, N1R vs WFR, N1R vs W2R, N1R vs EGTR, W2R vs FNR), con
bandas de control ±N sigma calculadas sobre la dispersión de los propios
puntos de correlación respecto a una curva ajustada (polinomio de grado 1–3
configurable).

- Requiere el archivo `Datos Correlacion.xlsx` junto a `app.py` (una hoja
  por variante: `LEAP-1A`, `LEAP-1B`), o se puede subir manualmente desde
  la UI si no se encuentra.
- Marca en rojo los puntos del motor que caen **fuera de banda** en cada
  par, con tabla detallada debajo de cada gráfica.
- **Puntos ocultos**: desde la tabla de "fuera de banda" se pueden
  seleccionar filas y ocultarlas con un motivo, eligiendo el alcance:
  - *Solo este par*: el punto sigue visible en los demás pares/correlaciones.
  - *Toda Correlación Ref.*: se excluye de los 6 pares de esta pestaña.
  - *Global*: se excluye de **toda la app** (todas las pestañas).
  Nada se borra de `motores.db`; el ocultamiento es reversible desde el
  panel "puntos ocultos" (con botones para restaurar uno por uno o todos a
  la vez, respetando el alcance).
- Para LEAP-1B, el EGTR del Excel de correlación viene en Kelvin y se
  convierte automáticamente a Celsius para poder compararlo.

### 5.4 Anomalías

Vista consolidada que recorre **todos** los parámetros del núcleo (respeta
los filtros de fecha/Description activos) y detecta:
- Outliers fuera de ±N sigma.
- Cruces de umbrales fijos guardados.
- Deriva CUSUM.
- Rachas largas.

Controles: N sigma, CUSUM k, CUSUM H, y el mismo selector de **baseline**
que en Tendencia (histórico completo / visible / rango manual / baseline
aprobado).

Cada anomalía tiene una fila editable con **Estado** (Pendiente / Revisada
/ Descartada) y **Nota** libre, que se guarda en `config.db` y persiste
entre sesiones (identificada por una "firma" estable del punto, no por su
posición en la tabla). Hay filtros locales por severidad, estado y tipo, y
métricas resumen (total, alta severidad, pendientes, revisadas).

### 5.5 Modificadores

Vigila que los **factores/modificadores de celda** (ej. `FMFN`, `FMEGT`,
`FMN2`, `FMW2`, `FMWF` para 1A; `CFFN`, `CFN2`, `CFEGT`, `CFw2A`, `CFWFM`
para 1B) se mantengan en **un solo nivel constante** dentro de cada rating
a lo largo de todo el histórico. **Ignora** los filtros de fecha/Description
del sidebar (siempre usa histórico completo).

Si dentro de un mismo rating aparece más de un nivel, significa que la
celda fue recalibrada entre esos reportes. Un slider de tolerancia (% del
valor) define qué tan distinto debe ser un valor para contarse como un
nivel nuevo. Muestra:
- Métricas globales (ratings analizados, modificadores vigilados, estables,
  con cambios).
- Una gráfica pequeña por modificador y rating, con líneas verticales
  marcando cada transición de nivel.
- Una tabla consolidada de todas las transiciones detectadas (útil para
  distinguir una recalibración real de celda —afecta a todos los
  ratings a la misma fecha— de un dato aislado que vale la pena revisar).

### 5.6 Eventos

Gestión de marcas temporales (actualizaciones de software, recalibraciones,
cambios de sensor, etc.) que luego se pueden dibujar en la gráfica de
Tendencia según su fecha.

- **Crear nuevo evento**: fecha, alcance (todas las variantes o solo una),
  nombre y descripción.
- **Lista de eventos existentes**: cada uno se puede editar (fecha, alcance,
  nombre, descripción) o borrar.

Se guardan en `config.db`.

### 5.7 Datos

Tabla con todas las mediciones filtradas (point_id, consecutivo,
Description, fecha, estado de parseo de fecha, número de punto, archivo de
origen, parámetro, valor, unidad).

**Retiro de puntos con cuarentena**:
1. Selecciona una o más filas de la tabla (multi-selección de filas).
2. Indica la carpeta donde están los Excel de origen.
3. Escribe el motivo del retiro (queda en el registro de cuarentena).
4. Pulsa "Retirar puntos y mover Exceles a cuarentena".

El comportamiento es **todo-o-nada**: si falta cualquier Excel de origen de
los puntos seleccionados, el retiro se bloquea por completo (no se toca
nada) a menos que se marque explícitamente la casilla "Permitir retirar
puntos aunque no se encuentre su Excel de origen". El Excel **nunca se
borra**: se mueve a la carpeta `quarantine/` junto a la app, y queda
registrado en un historial (visible en el expander "Historial de
cuarentena") con archivo, ruta de cuarentena, puntos afectados y motivo.
Para reincorporar un Excel puesto en cuarentena, se mueve de vuelta a la
carpeta de origen y se vuelve a correr el ETL.

---

## 6. Corrección de unidades (kg/h → lb/h)

Algunos reportes de flujo de combustible capturaron el número en kg/h
aunque la unidad guardada ya dice `pph` (la etiqueta es correcta, el dato
está mal). Las reglas de corrección (variante + parámetro + ventana de
fechas) están centralizadas en `services/unit_corrections.py`.

Cada vista que puede mostrar un parámetro afectado (Tendencia, Correlación,
Correlación Ref.) muestra su propio checkbox **"Aplicar corrección kg/h →
lb/h"** solo cuando el parámetro seleccionado en esa vista cae en una regla
activa. Está **desactivado por defecto** para no alterar el dato crudo sin
que el usuario lo note explícitamente.

---

## 7. Exportación de reportes

Desde la pestaña Tendencia (modo un solo parámetro), al fondo de la página:
- **Descargar Excel**: datos, estadísticas (media, sigma, UCL/LCL,
  regresión si aplica) y la gráfica embebida.
- **Descargar PDF**: mismo contenido en formato reporte imprimible.

Ambos incluyen metadatos (variante, parámetro, Description, rango de
fechas, fecha de generación) y la configuración de filtros/bandas/umbrales
usada al momento de exportar.

---

## 8. Dónde vive cada dato

| Dato | Archivo | Se versiona en git |
|---|---|---|
| Mediciones de motores (ingeridas por el ETL) | `data/motores.db` | No |
| Configuración de usuario (vistas favoritas, umbrales, eventos, puntos ocultos, baselines aprobados, estados de anomalías, historial de cuarentena) | `config.db` | No |
| Diccionario de nombres crudos → canónicos | `mapping.yaml` | Sí |
| Excel de correlación de referencia | `Datos Correlacion.xlsx` (junto a `app.py`) | No |
| Excel movidos a cuarentena | carpeta `quarantine/` | No |

`config.db` se crea solo la primera vez que se usa alguna función que
necesite guardar configuración.

---

## 9. Preguntas frecuentes

**No aparece nada al abrir la app / "No se encontró la base".**
Falta correr el ETL (sección 3.1) para generar `data/motores.db`.

**Agregué un parámetro nuevo a `mapping.yaml` pero no aparece en los
reportes ya cargados.**
Corre `resync_measurements.py` (sección 3.1); el ETL normal no reprocesa
archivos ya ingeridos.

**Las bandas / umbrales no se pueden definir.**
Filtra la barra lateral a un solo valor de "Rating / Punto" (Description);
mezclar ratings distintos no tiene sentido estadístico para una sola media.

**Oculté un punto en Correlación Ref. y sigue apareciendo en Tendencia.**
Revisa el alcance con el que se ocultó: "Solo este par" y "Toda Correlación
Ref." no afectan otras pestañas; solo el alcance "Global" se excluye de
toda la app.

**Retiré un punto por error.**
El Excel de origen no se borra, solo se mueve a `quarantine/`. Muévelo de
vuelta a la carpeta original y vuelve a correr el ETL para recuperarlo.

---

## 10. Pruebas (para quien mantiene el proyecto)

```
pip install pytest
pytest
```

Cubre principalmente la lógica de `services/unit_corrections.py` y
`config_store.py` (sin dependencias de Streamlit).
