import pytest
from pydantic import ValidationError

from app.models import ClasificacionInput, ClasificacionOutput


def test_input_requiere_denominacion():
    with pytest.raises(ValidationError):
        ClasificacionInput.model_validate({"monto": 100.0})


def test_input_rechaza_denominacion_vacia():
    with pytest.raises(ValidationError):
        ClasificacionInput(denominacion="   ")


def test_input_normaliza_y_acepta_extras():
    entrada = ClasificacionInput.model_validate(
        {"denominacion": "  Notebook Dell  ", "monto": "1500.5", "proveedor": "Dell", "orden_compra": "OC-1"}
    )
    assert entrada.denominacion == "Notebook Dell"
    assert entrada.monto == 1500.5
    assert entrada.contexto_adicional() == {"monto": 1500.5, "proveedor": "Dell", "orden_compra": "OC-1"}


def test_input_monto_invalido():
    with pytest.raises(ValidationError):
        ClasificacionInput.model_validate({"denominacion": "x", "monto": "mucho"})


def test_output_valido():
    out = ClasificacionOutput.model_validate(
        {
            "clase_sugerida": 53000010,
            "denominacion_sugerida": "Notebook Lenovo ThinkPad T14",
            "confianza": "media",
            "justificacion": "ok",
            "alternativas": [{"clase": 53000020, "motivo": "similar"}],
        }
    )
    assert out.alternativas[0].clase == 53000020


def test_output_rechaza_denominacion_mayor_a_50():
    with pytest.raises(ValidationError):
        ClasificacionOutput.model_validate(
            {
                "clase_sugerida": 53000010,
                "denominacion_sugerida": "x" * 51,  # TXT50 de SAP admite 50 caracteres
                "confianza": "alta",
                "justificacion": "ok",
                "alternativas": [],
            }
        )


@pytest.mark.parametrize(
    "cambio",
    [
        {"confianza": "muy alta"},
        {"clase_sugerida": "no-numero"},
        {"alternativas": [{"clase": 53000020}]},  # falta motivo
    ],
)
def test_output_rechaza_esquema_invalido(cambio):
    base = {
        "clase_sugerida": 53000010,
        "denominacion_sugerida": "Notebook",
        "confianza": "alta",
        "justificacion": "ok",
        "alternativas": [],
    }
    with pytest.raises(ValidationError):
        ClasificacionOutput.model_validate({**base, **cambio})


def test_output_campos_requeridos_en_schema():
    schema = ClasificacionOutput.model_json_schema()
    assert set(schema["required"]) == {
        "clase_sugerida",
        "denominacion_sugerida",
        "confianza",
        "justificacion",
        "alternativas",
    }
    assert schema["properties"]["confianza"]["enum"] == ["alta", "media", "baja"]
