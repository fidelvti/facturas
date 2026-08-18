# Facturas

Aplicación local para almacenar, consultar e incorporar automáticamente datos de facturas y otros gastos personales.

El proyecto sustituye un Excel histórico mantenido manualmente por una base de datos SQLite y añade ingestión automática de nuevos documentos y un dashboard en Streamlit.

## Proveedores soportados

Actualmente se procesan:

- Agua
- Gas
- Luz
- Nóminas GFT
- Pagatelia

Cada proveedor tiene su propio parser y modelo de datos. No se intenta homogeneizar información que conceptualmente es diferente.

## Histórico

Los datos históricos proceden de:

```text
data/_Facturas.xlsx
```

y fueron migrados a:

```text
data/facturas.sqlite3
```

El histórico migrado se considera **autoritativo**.

No se recalculan ni reconcilian las facturas históricas contra sus documentos originales.

La ingestión automática solo se aplica a documentos nuevos posteriores a la activación del scanner.

## Organización de `_print`

La carpeta de documentos se organiza en dos zonas:

```text
_print/
├── inbox/
│   ├── agua/
│   ├── gas/
│   ├── luz/
│   ├── gft/
│   ├── pagatelia/
│   └── phone/
└── archivo/
    └── YYYY/
```

`_print/inbox` es el área activa. El scanner solo procesa documentos nuevos dentro de sus subcarpetas de proveedor.

`_print/archivo/YYYY` contiene ejercicios cerrados y no se escanea.

Estas carpetas manuales pueden existir bajo `_print`, pero quedan fuera del sistema automático y no se tocan:

- `movistar+`
- `alarma`
- `vida_laboral`
- `tickets`

La carpeta `phone` está organizada dentro de `inbox`, pero todavía no se ingiere automáticamente.

## Ejercicio actual

El año de negocio para los documentos activos se guarda en SQLite en la opción `current_year`.

Por defecto, una base nueva inicializa:

```text
current_year = 2026
```

El mes sale del nombre del fichero y el año sale de `current_year`.

## Convención de nombres activos

El periodo de negocio lo determina siempre el **nombre del fichero**, independientemente de las fechas impresas dentro del documento.

Formato:

```text
aguaXX.pdf
gasXX.pdf
luzXX.pdf
gftXX.pdf
pagateliaXX.pdf
pagateliaXX-N.pdf
```

`XX` es el mes.

Ejemplos para 2026:

```text
agua08.pdf -> 202608
gas10.pdf  -> 202610
luz12.pdf  -> 202612
gft09.pdf  -> 202609
pagatelia04.pdf   -> 202604
pagatelia04-2.pdf -> 202604
```

Pagatelia ya no usa el año en los nombres activos. Los nombres históricos tipo `PagateliaYYMM.pdf` no son la convención activa.

## Instalación

Instalar las dependencias:

```bash
python3 -m pip install -r requirements.txt
```

## Uso habitual

### Procesar nuevas facturas

Desde la raíz del proyecto:

```bash
python3 -m facturas.scan "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Data/_print" --database data/facturas.sqlite3
```

También puede recibir directamente la carpeta activa:

```bash
python3 -m facturas.scan "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Data/_print/inbox" --database data/facturas.sqlite3
```

Este es el comando habitual para incorporar las nuevas facturas.

El scanner:

- ignora los documentos anteriores a su fecha de activación;
- escanea solo `_print/inbox` cuando se le pasa `_print`;
- no entra en `_print/archivo`;
- no procesa las carpetas manuales excluidas ni `inbox/phone`;
- ignora los nombres de fichero no soportados;
- procesa únicamente documentos nuevos reconocidos;
- evita duplicados mediante SHA256;
- continúa procesando otros documentos si uno requiere revisión manual.

Los archivos existentes antes de la activación pertenecen al histórico y no se vuelven a procesar.

### Ingestión manual

Para procesar explícitamente un fichero concreto:

```bash
python3 -m facturas.ingest "/ruta/al/fichero.pdf" --database data/facturas.sqlite3
```

Por ejemplo:

La ingestión manual sirve como vía alternativa cuando se quiere procesar expresamente un documento concreto.

### Cierre anual

El cierre anual es solo organización de ficheros. No ingiere ni parsea PDFs.

Por defecto se ejecuta en modo simulación:

```bash
python3 -m facturas.close_year "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Data/_print" --database data/facturas.sqlite3
```

Para aplicar los movimientos:

```bash
python3 -m facturas.close_year "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Data/_print" --database data/facturas.sqlite3 --apply
```

Con `--apply`, mueve los ficheros de `inbox/<proveedor>/` a `archivo/<current_year>/<proveedor>/`, conserva las carpetas de `inbox` preparadas para el siguiente ejercicio y avanza `current_year` en SQLite.

## Dashboard

Arrancar Streamlit:

```bash
python3 -m streamlit run app.py
```

Por defecto estará disponible en:

```text
http://localhost:8501
```

El dashboard es actualmente de solo lectura y mantiene completamente separadas las áreas de cada proveedor:

- Agua
- Gas
- Luz
- Nóminas
- Pagatelia

Solo se muestran datos con significado de negocio. Se ocultan IDs, hashes, claves internas, estados técnicos, información de migración y demás metadatos internos.

Las tablas se muestran desde el periodo más reciente al más antiguo.

Los gráficos temporales se muestran cronológicamente desde el periodo más antiguo al más reciente.

### Agua

Muestra una tabla con los datos disponibles y gráficos de evolución de:

- consumo de agua en m³;
- importe total de las facturas.

### Gas

Muestra por separado las tablas de:

- Potencia / plazo fijo
- Consumo
- Otros

Incluye gráficos de evolución de:

- precio del plazo fijo;
- precio unitario utilizado para calcular el consumo.

Si dentro de un mismo periodo existen varios precios, se conservan todas las observaciones. No se calculan medias ni se eliminan valores.

### Luz

Muestra por separado las tablas de:

- Potencia
- Consumo / energía
- Otros

Incluye gráficos de evolución de:

- precio unitario de potencia;
- precio unitario de energía.

Si dentro de un mismo periodo existen varios precios, se muestran todos. No se agregan ni promedian.

### Nóminas

Muestra una tabla con los datos de negocio disponibles, incluyendo:

- Periodo
- Guardias
- Gastos
- Dietas
- Bonus
- Total
- IRPF (%)

Los conceptos opcionales pueden estar vacíos. Un valor ausente no se convierte artificialmente en cero.

### Pagatelia

Muestra una tabla con:

- Periodo
- Importe
- Total
- Factura

Los movimientos con el mismo importe se agrupan.

La regla es:

```text
FACTURA = IMPORTE × TOTAL
```

Por ejemplo, tres movimientos de 4,89 € se representan como:

```text
IMPORTE = 4,89
TOTAL   = 3
FACTURA = 14,67
```

No se distingue entre peajes, parkings, cuotas del servicio u otros conceptos de Pagatelia. Para esta aplicación todos son gastos Pagatelia.

## Extracción de documentos

Siempre que el PDF contiene una capa de texto utilizable, se utiliza extracción directa.

El OCR queda como mecanismo de fallback para documentos cuyo texto no pueda extraerse de forma fiable.

Los parsers son específicos para cada proveedor y están deliberadamente orientados a los formatos reales utilizados por esta aplicación.

No se pretende construir un sistema genérico de interpretación de facturas.

## Tests

Ejecutar la suite completa:

```bash
python3 -m unittest discover -v
```

## Activación del scanner

El scanner necesita una activación inicial para establecer la frontera entre los documentos históricos y los nuevos:

```bash
python3 -m facturas.scan "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Data/_print" --database data/facturas.sqlite3 --activate
```

La activación:

- guarda el momento de puesta en marcha;
- procesa cero documentos existentes;
- considera histórico todo lo anterior a ese momento.

**Este comando solo debe utilizarse para la activación inicial.**

En la instalación actual el scanner ya está activado, por lo que normalmente **no debe volver a ejecutarse**.

El uso cotidiano es simplemente:

```bash
python3 -m facturas.scan "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Data/_print" --database data/facturas.sqlite3
```

## Estructura básica del proyecto

```text
facturas/
├── app.py
├── facturas/
│   ├── db.py
│   ├── ingest.py
│   ├── scan.py
│   ├── dashboard_data.py
│   └── extractors/
│       ├── electricity.py
│       ├── gas.py
│       ├── water.py
│       ├── payroll.py
│       └── pagatelia.py
├── data/
│   ├── _Facturas.xlsx
│   └── facturas.sqlite3
├── samples/
├── tests/
├── requirements.txt
└── README.md
```

## Datos locales

La base SQLite, el Excel histórico, las facturas y demás datos personales son datos locales y no deben versionarse en Git.

El directorio `data/` está excluido del repositorio.

La carpeta `samples/` se mantiene vacía y puede conservarse mediante `.gitkeep`.
