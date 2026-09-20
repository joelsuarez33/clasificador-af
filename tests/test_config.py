import json

import pytest

from app.config import REQUIRED_VARS, ConfigError, load_settings

OPCIONALES = ("TOP_K", "API_PORT", "EMBEDDING_DIM", "BQ_TABLA_HISTORICO", "BQ_TABLA_POLITICA", "BQ_VECTOR_INDEX")


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    for var in (*REQUIRED_VARS, *OPCIONALES):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def sa_json(tmp_path):
    ruta = tmp_path / "sa.json"
    ruta.write_text(
        json.dumps({"type": "service_account", "client_email": "sa@p.iam.gserviceaccount.com", "private_key": "k"}),
        encoding="utf-8",
    )
    return ruta


def _env(tmp_path, **valores):
    ruta = tmp_path / ".env"
    ruta.write_text("\n".join(f"{k}={v}" for k, v in valores.items()), encoding="utf-8")
    return ruta


def test_configuracion_valida(tmp_path, sa_json):
    env = _env(tmp_path, GCP_PROJECT_ID="mi-proyecto", BQ_DATASET="activos", GOOGLE_APPLICATION_CREDENTIALS=sa_json)
    s = load_settings(env, exportar_credenciales=False)
    assert s.tabla_historico_fq == "mi-proyecto.activos.af_historico_embeddings"
    assert s.credentials_path == sa_json
    assert s.gemini_model == "gemini-2.5-flash"


def test_faltan_variables_mensaje_explicito(tmp_path):
    env = _env(tmp_path, GCP_PROJECT_ID="mi-proyecto")
    with pytest.raises(ConfigError) as exc:
        load_settings(env, exportar_credenciales=False)
    assert "BQ_DATASET" in str(exc.value)
    assert "GOOGLE_APPLICATION_CREDENTIALS" in str(exc.value)


def test_credenciales_inexistentes(tmp_path):
    env = _env(tmp_path, GCP_PROJECT_ID="mi-proyecto", BQ_DATASET="activos",
               GOOGLE_APPLICATION_CREDENTIALS=tmp_path / "no-existe.json")
    with pytest.raises(ConfigError, match="inexistente"):
        load_settings(env, exportar_credenciales=False)


def test_credenciales_no_service_account(tmp_path):
    ruta = tmp_path / "user.json"
    ruta.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
    env = _env(tmp_path, GCP_PROJECT_ID="mi-proyecto", BQ_DATASET="activos", GOOGLE_APPLICATION_CREDENTIALS=ruta)
    with pytest.raises(ConfigError, match="service_account"):
        load_settings(env, exportar_credenciales=False)


def test_dataset_invalido_no_se_interpola_en_sql(tmp_path, sa_json):
    env = _env(tmp_path, GCP_PROJECT_ID="mi-proyecto", BQ_DATASET="x`; DROP", GOOGLE_APPLICATION_CREDENTIALS=sa_json)
    with pytest.raises(ConfigError, match="BQ_DATASET"):
        load_settings(env, exportar_credenciales=False)
