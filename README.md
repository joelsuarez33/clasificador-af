# Clasificador de Activos Fijos (AF)

Librería Python que sugiere la **clase de activo fijo** del *Daimler Group Asset Class Catalogue* para una
denominación de activo. Usa como evidencia los precedentes históricos ya clasificados.

- **Retrieval:** BigQuery Vector Search sobre ~14.400 activos históricos embebidos con Vertex AI `text-embedding-005`.
- **Clasificación:** Gemini `gemini-2.5-flash` (Vertex AI, SDK `google-genai`) con salida JSON estructurada.
- **Garantía:** la clase devuelta **siempre** es un código del catálogo oficial. Si el modelo propone un código
  inexistente, se le reinyecta el error hasta 2 veces. Si aun así falla, se devuelve la clase más votada entre los
  precedentes con `confianza: "baja"` y `fallback: true`.
- **Se usa como librería:** `app.classifier_core.clasificar()` devuelve una sola línea (`"52000340 - Maquinas … CNC"`) para
  insertar en un campo de SAP. La versión con confianza, justificación y precedentes es `clasificar_detallado()`.

```
Politica_AF.xlsx ──► preprocess/load_catalogo.py ──► data/catalogo.json + BQ politica_af
AF_definitivos_creados.xlsx ──► preprocess/build_index.py ──► BQ af_historico_embeddings + VECTOR INDEX

clasificar() ─► retrieval (VECTOR_SEARCH) ─► prompt_builder (catálogo + precedentes) ─► classifier (Gemini + validación) ─► "52000340 - Maquinas … CNC"
```

## Estructura

```
clasificador-af/
├── app/
│   ├── config.py          # .env + validación de variables y Service Account
│   ├── gcp.py             # clientes Vertex AI / BigQuery con credenciales explícitas
│   ├── models.py          # Pydantic: ClasificacionInput / ClasificacionOutput / ...
│   ├── catalogo.py        # catálogo en memoria (data/catalogo.json)
│   ├── embeddings.py      # limpieza de texto + embeddings con batching y reintentos
│   ├── retrieval.py       # buscar_precedentes() con VECTOR_SEARCH
│   ├── prompt_builder.py  # prompt de sistema (reglas + catálogo) y de usuario (activo + precedentes)
│   ├── classifier.py      # Gemini + validación de código + reintentos con tenacity + fallback
│   └── classifier_core.py # ENTRADA PRINCIPAL: clasificar_af() / clasificar() / clasificar_detallado()
├── preprocess/
│   ├── load_catalogo.py   # Politica_AF.xlsx -> catalogo.json + tabla politica_af
│   └── build_index.py     # AF_definitivos_creados.xlsx -> embeddings + VECTOR INDEX (incremental)
├── data/                  # Excel fuente + catalogo.json generado
├── sap/                   # automatización SAP GUI (ME53N -> AS01) + _debug_columnas.py
├── scripts/               # demo.py (demo interactiva)
├── secrets/               # (opcional) JSON de Service Account; ignorado por git
├── tests/                 # pytest con dobles de Vertex AI y BigQuery (sin llamadas reales)
├── pyproject.toml         # dependencias con piso de versión, requires-python >= 3.12
├── setup.sh / setup.ps1   # setup reproducible Linux-macOS / Windows
└── .env.example
```

## Requisitos

- **Python >= 3.12** (probado en 3.12 y en 3.14). `pyproject.toml` declara `requires-python = ">=3.12"`, sin techo:
  `pip install` falla solo con versiones anteriores. El entorno se crea con `setup.ps1` / `setup.sh`.
  - Windows: `winget install -e --id Python.Python.3.12` (o una versión superior), o el instalador de python.org
    (marcá *Add python.exe to PATH*). Si tenés varias versiones instaladas, el launcher `py -3` elige una;
    `setup.ps1` lo usa automáticamente y verifica que sea >= 3.12.
  - macOS: `brew install python@3.12` o superior.
  - Ubuntu/Debian: `sudo apt install python3.12 python3.12-venv` o superior (en versiones viejas, PPA `deadsnakes`).
  - pyenv: `pyenv install 3.14`. El repo trae `.python-version` y pyenv lo toma solo.
  - En 3.14 los pisos de dependencias importan: `pydantic >= 2.12`, `grpcio >= 1.75.1` y `pywin32 >= 311` son las
    primeras versiones con wheels para cp314.
- Un proyecto de GCP con las APIs **Vertex AI** (`aiplatform.googleapis.com`) y **BigQuery** (`bigquery.googleapis.com`) habilitadas.
- Un **JSON de Service Account** provisto por el administrador de GCP. El código no genera credenciales ni abre
  flujos de navegador: tampoco usa `gcloud auth login`.

### Roles IAM de la Service Account

| Rol | Dónde | Para qué |
|---|---|---|
| `roles/aiplatform.user` (Vertex AI User) | Proyecto | Embeddings (`text-embedding-005`) y Gemini |
| `roles/bigquery.jobUser` (BigQuery Job User) | Proyecto | Ejecutar consultas, cargas y `VECTOR_SEARCH` |
| `roles/bigquery.dataEditor` (BigQuery Data Editor) | Dataset (o proyecto si el dataset aún no existe) | Crear el dataset y las tablas, cargar datos, crear el `VECTOR INDEX` |

En producción, el clasificador solo necesita `roles/bigquery.dataViewer` sobre el dataset. `dataEditor` hace falta únicamente
para correr `preprocess/`.

## Setup paso a paso

1. **Credenciales.** Guardá el JSON de Service Account, **preferentemente fuera del repo** (ej. `C:\credenciales\rag-af-sa.json`
   o `~/.config/gcp/rag-af-sa.json`). Si lo dejás dentro del repo, ponelo en `secrets/`: git lo ignora.
2. **Variables.** Copiá `.env.example` a `.env` y completá:
   ```
   GCP_PROJECT_ID=mi-proyecto
   BQ_DATASET=activos_fijos
   GOOGLE_APPLICATION_CREDENTIALS=C:/credenciales/rag-af-sa.json   # ruta absoluta
   ```
   Las opcionales (región, modelos, nombres de tabla) están documentadas en `.env.example`.
3. **Instalación.** Hace falta conexión a internet.
   - Windows: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
   - Linux/macOS: `chmod +x setup.sh && ./setup.sh`

   El script verifica Python >= 3.12, crea `.venv`, instala las dependencias (`pip install -e ".[dev]"`),
   comprueba los imports, corre los tests y valida la configuración con `python -m app.config`.
4. **Fuentes de datos.** Deben estar en `data/` como `Politica_AF.xlsx` y `AF_definitivos_creados.xlsx`. Otras rutas se
   configuran con `POLITICA_AF_XLSX` y `AF_HISTORICO_XLSX`.
5. **Catálogo** (se repite cada vez que cambie la política):
   ```
   python -m preprocess.load_catalogo          # genera data/catalogo.json y carga BQ politica_af
   python -m preprocess.load_catalogo --sin-bq # solo el JSON
   ```
6. **Índice vectorial.** Es incremental: solo embebe las filas nuevas.
   ```
   python -m preprocess.build_index            # incremental
   python -m preprocess.build_index --prune    # además borra lo que ya no está en el Excel
   python -m preprocess.build_index --full-refresh  # regenera todo (p. ej. si cambia el modelo de embeddings)
   python -m preprocess.build_index --dry-run  # solo parsea y muestra estadísticas
   ```
7. **Probar una clasificación:**
   ```
   .venv\Scripts\python -m app.classifier_core "Torno CNC" --monto 50000
   ```

## Uso desde otro script (caso principal)

Es una librería: se importa, no se expone por HTTP. La automatización de SAP (`sap/`) la llama así:

```python
from app.classifier_core import clasificar_af

c = clasificar_af("Corrugadora Tansen linea completa", monto=120000, centro_costo="CC-4100")
c.clase_sugerida          # 52000660
c.denominacion_sugerida   # 'Línea completa de corrugado industrial'  (máx. 50 chars, para TXT50)
c.confianza               # 'alta' | 'media' | 'baja'
c.justificacion
```

También hay una variante que devuelve **una sola línea**, lista para escribir en un campo de texto:

```python
from app.classifier_core import clasificar

linea = clasificar("Torno CNC", monto=50000)
# '52000340 - Maquinas (del rubro maquinarias I) CNC'
```

Solo `denominacion` es obligatoria. Cualquier dato extra (`monto`, `centro_costo`, `proveedor`, o campos propios)
se le pasa al modelo como contexto. Opciones de formato de la línea:

```python
clasificar("Torno CNC", solo_codigo=True)      # '52000340'
clasificar("Torno CNC", separador=" | ")       # '52000340 | Maquinas (del rubro maquinarias I) CNC'
clasificar("Torno CNC", max_largo=40)          # recorta a 40 caracteres
```

La primera llamada crea los clientes y carga el catálogo; las siguientes reutilizan todo
(`get_clasificador()` está cacheado), así que conviene clasificar varios activos en el mismo proceso.

### Versión detallada (opcional)

Misma clasificación, con la evidencia, para auditar o mostrar en pantalla:

```python
from app.classifier_core import clasificar_detallado

r = clasificar_detallado("Torno CNC", monto=50000)
r.clase_sugerida   # 52000340
r.descripcion_clase
r.confianza        # 'alta' | 'media' | 'baja'
r.justificacion
r.alternativas     # [AlternativaClase(clase=..., motivo=...), ...]
r.precedentes      # históricos usados como evidencia, con su distancia
r.fallback         # True: la clase salió del voto de precedentes; revisar a mano
```

### Desde la consola

```
.venv\Scripts\python -m app.classifier_core "Torno CNC" --monto 50000     # imprime la línea
.venv\Scripts\python -m app.classifier_core "Torno CNC" --solo-codigo
.venv\Scripts\python -m app.classifier_core "Torno CNC" --detalle          # JSON completo
.venv\Scripts\python scripts\demo.py                                # demo interactiva
```

Códigos de salida: `0` OK, `2` error de configuración o sin clase válida (el detalle va a stderr).

## Automatización SAP (`sap/`)

- `sap_me53n_as01t.py`: lee la solicitud de pedido en ME53N, captura la pantalla al portapapeles, muestra un
  formulario de revisión humana y completa AS01. Con `MODO_SIMULACION = True` completa la pantalla y **no graba**.
- `_debug_columnas.py`: utilitario de diagnóstico. Imprime el `ColumnOrder` del grid de posiciones de ME53N, que es
  lo que hace falta para leer varias posiciones. Requiere SAP GUI abierto y `pip install -e ".[sap]"`
  (equivale a `pip install "pywin32>=311" "pillow>=11.3"`; en 3.14 los pisos son obligatorios).

  ```
  .venv\Scripts\python sap\_debug_columnas.py 10012345 --valores 3
  ```

La clase de activo `ANLKL` sale de `DEFAULTS_AS01` y es constante por decisión de negocio: **no** la define el
clasificador.

### Errores a contemplar en el script que la llama

| Excepción | Cuándo |
|---|---|
| `app.config.ConfigError` | Falta una variable del `.env` o el JSON de Service Account no es legible |
| `app.classifier.ClasificacionFallidaError` | Ni el modelo ni los precedentes dieron una clase del catálogo: requiere clasificación manual |
| `google.genai.errors.APIError`, `google.api_core.exceptions.GoogleAPIError` | Falla de Vertex AI o BigQuery tras los reintentos automáticos |


## Tests

```
python -m pytest                                   # toda la suite, sin llamadas a GCP
python -m pytest tests/test_classifier.py -k invalida   # un test puntual
```

## Migrar a otra PC

1. Instalá **Python >= 3.12** en la PC nueva (ver *Requisitos*).
2. Copiá:
   - **El repo completo**, incluido `data/`. No hace falta copiar `.venv/`: se recrea.
   - **El `.env`** con sus valores.
   - **El JSON de Service Account** en la ruta que indique `GOOGLE_APPLICATION_CREDENTIALS` en el `.env`. Si la ruta
     cambia en la PC nueva (otro usuario u otra unidad), actualizá el `.env`.
3. Con internet, corré `setup.ps1` (Windows) o `setup.sh` (Linux/macOS).
4. Verificá con `python -m app.config`. Las tablas de BigQuery ya existen en la nube, así que **no hace falta**
   re-correr `preprocess/` salvo que cambien los Excel.
