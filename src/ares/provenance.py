"""Procedencia doble de cada dato: etiqueta (MED/CALC/EST/EXP) + origen
(ARES/WHOOP/COROS/INTERVALS/TREDICT), tal como fija el Implementation Plan v0.3 FINAL (§4).

No es un tipo de dato que se guarde suelto: se usa para anotar `signals` en `decisions`
y los campos `hrv_tag`/`hrv_origin` de `daily_metrics`. Este módulo solo fija el
vocabulario y valida que no se usen etiquetas u orígenes inventados sobre la marcha.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

Tag = Literal["MED", "CALC", "EST", "EXP"]
Origin = Literal["ARES", "WHOOP", "COROS", "INTERVALS", "TREDICT"]

VALID_TAGS: tuple[Tag, ...] = ("MED", "CALC", "EST", "EXP")
VALID_ORIGINS: tuple[Origin, ...] = ("ARES", "WHOOP", "COROS", "INTERVALS", "TREDICT")


class Provenance(NamedTuple):
    tag: Tag
    origin: Origin

    def __str__(self) -> str:
        return f"{self.tag} · {self.origin}"


def provenance(tag: str, origin: str) -> Provenance:
    if tag not in VALID_TAGS:
        raise ValueError(f"Etiqueta desconocida: {tag!r}. Válidas: {VALID_TAGS}")
    if origin not in VALID_ORIGINS:
        raise ValueError(f"Origen desconocido: {origin!r}. Válidos: {VALID_ORIGINS}")
    return Provenance(tag, origin)  # type: ignore[arg-type]


# Combinaciones ya decididas en la especificación, para no repetirlas sueltas por el código.
WHOOP_HRV = provenance("MED", "WHOOP")  # rMSSD nocturno del proveedor (Especificación v0.3)
ARES_LN_RMSSD = provenance("CALC", "ARES")  # ln rMSSD que ARES calcula sobre ese valor
MEASURED_SUBJECTIVE = provenance("MED", "ARES")  # registro diario (dato del usuario)
