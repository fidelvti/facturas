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

## Convención de nombres

El periodo de negocio lo determina siempre el **nombre del fichero**, independientemente de las fechas impresas dentro del documento.

### Agua, Gas, Luz y GFT

Formato:

```text
aguaXX.pdf
gasXX.pdf
luzXX.pdf
gftXX.pdf
```

`XX` es el mes.

Ejemplos para 2026:

```text
agua08.pdf -> 202608
gas10.pdf  -> 202610
luz12.pdf  -> 202612
gft09.pdf  -> 202609
```

### Pagatelia

Pagatelia incluye el año y el mes en el nombre:

```text
PagateliaYYMM.pdf
```

Por ejemplo:

```text
Pagatelia2608.pdf -> 202608
```

Puede haber más de una factura Pagatelia correspondiente al mismo periodo. En ese caso se permiten sufijos:

```text
Pagatelia2305a.pdf -> 202305
Pagatelia2305b.pdf -> 202305
```

El sufijo no altera el periodo.

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

Este es el comando habitual para incorporar las nuevas facturas.

El scanner:

- ignora los documentos anteriores a su fecha de activación;
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

```bash
python3 -m facturas.ingest "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Data/_print/luz09.pdf" --database data/facturas.sqlite3
```

La ingestión manual sirve como vía alternativa cuando se quiere procesar expresamente un documento concreto.

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
