# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Python **>= 3.12** (`requires-python = ">=3.12"`, no upper bound). The default `python` on this Windows machine is 3.14 and the project runs on it. Dependency floors that 3.14 needs: `pydantic>=2.12`, `grpcio>=1.75.1`, `pywin32>=311` (first versions with cp314 wheels).

```
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # create .venv, pip install -e ".[dev]", run tests and config check
.venv\Scripts\python -m pytest                          # all tests (no GCP calls)
.venv\Scripts\python -m pytest tests/test_classifier.py -k invalida   # single test
.venv\Scripts\python -m app.config                      # validate .env and the Service Account without printing secrets
.venv\Scripts\python -m preprocess.load_catalogo [--sin-bq]
.venv\Scripts\python -m preprocess.build_index [--prune | --full-refresh | --dry-run]
.venv\Scripts\python -m app.classifier_core "Torno CNC" [--detalle | --solo-codigo]   # one classification
.venv\Scripts\python scripts\demo.py                    # interactive demo
.venv\Scripts\python sap\_debug_columnas.py 10012345    # prints the ME53N item grid ColumnOrder (needs SAP GUI)
```

## Architecture

The pipeline is linear on purpose (no agent frameworks):

- **Offline (`preprocess/`)**
  - `load_catalogo` turns `data/Politica_AF.xlsx` (sheet "Test Version") into `data/catalogo.json`, which the app reads at startup, and into the BigQuery table `politica_af`.
  - `build_index` turns `data/AF_definitivos_creados.xlsx` into `af_historico_embeddings` and builds its `VECTOR INDEX`.
- **Online (`app/`), in `classifier_core.ClasificadorAF`:** `retrieval.buscar_precedentes` → `prompt_builder` → `classifier.Clasificador`.
  - **`app/classifier_core.py` is the entry point, as a library.** There is no HTTP layer: `app/main.py` (FastAPI) was deleted on purpose, along with fastapi/uvicorn/httpx. Don't reintroduce them.
  - `clasificar_af(denominacion, monto, centro_costo) -> ClasificacionOutput` is what `sap/` calls. `clasificar()` returns one line (`"52000340 - Maquinas … CNC"`, via `formatear_linea`) and `clasificar_detallado()` the full `ClasificacionRespuesta`. `get_clasificador()` is `lru_cache`d, so clients and catalog load once per process.
- **SAP (`sap/sap_me53n_as01t.py`):** working script, tested against real SAP GUI (ME53N → screenshot → review form → AS01, with `MODO_SIMULACION`). Extend it; don't restructure or restyle it. `ANLKL` comes from `DEFAULTS_AS01` by business decision and must stay independent of the classifier.
- **Invariant:** a response never contains a class code that isn't in the catalog.
  - `classifier` validates the code and retries up to 2 times, re-injecting the error into the conversation history (tenacity `Retrying`).
  - If that fails, it falls back to a similarity-weighted vote over precedents, excluding out-of-catalog classes, and returns `confianza="baja"` with `fallback=True`.
  - If no precedent class is valid either, it raises `ClasificacionFallidaError`.
  - Invalid alternatives are dropped silently.
  - `denominacion_sugerida` (max 50 chars, for SAP's TXT50) is part of the Gemini response schema. On fallback it comes from the input text, since there is no model answer.
- **Shared text cleaning:** `app/embeddings.py` holds the cleaning used by both indexing and querying. `normalizar_denominacion` keeps the text for display; `limpiar_denominacion` lowercases it for embedding. If you change it, run `build_index --full-refresh`.
- **Auth:** `app/gcp.crear_clientes` builds both clients from the Service Account file with explicit credentials. There is never an ADC or gcloud user fallback.
- **Config:** `app/config.load_settings` validates the env vars and the SA JSON. It also restricts project, dataset and table identifiers to a strict format because they are interpolated into SQL.

## Data quirks

- **Catalog codes:** only 8-digit ints are catalog codes.
  - Rows like `"0051000 000"` are group headers.
  - Rows with no code are section or sub-headers and feed the `rubro` field.
  - Rows starting with "Clave:" are notes.
  - The real sheet has 179 classes and one duplicate code (53000040), of which the first occurrence is kept.
- **History:** only about 3.5k of the ~14.4k rows are unique `(clase, denominacion_limpia)` pairs, and dedup is keyed on `row_id = sha256(clase|limpia)`. That puts the table under 5k rows, so BigQuery may not use the IVF index and falls back to exact search.
- **Out-of-catalog classes:** 8 classes in the history aren't in the catalog. They are kept as precedents but marked `[FUERA DE CATÁLOGO]` in the prompt, and they are never eligible as an answer.
- **Tests:** they use fakes from `tests/conftest.py` (`FakeGenaiClient`, `respuesta_json`). Nothing in the suite touches GCP or SAP.
