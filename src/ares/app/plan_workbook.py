"""Importación controlada de un Excel maestro ARES descargado de Drive.

Solo STL: lectura XLSX mediante ZIP+XML, jamás ejecuta macros.
Sin credenciales Drive: el usuario exporta el fichero, revisa diferencias
y aplica mediante --apply. Solo S32-S40 del snapshot autorizado.
Cambios atómicos con copia de seguridad; no modifica el Excel original.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from . import planning

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COL_RE = re.compile(r"([A-Z]+)[0-9]+")
DAY_NAMES = ("LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM")
FIELDS = (
    "date", "weekday", "type", "title", "detail", "notes",
    "duration_min", "km_estimate", "shoe", "during_fuel",
    "alert", "strength_min",
)


class ImportErrorPlan(ValueError):
    pass


def _norm(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value.upper())
        if not unicodedata.combining(ch)
    ).strip()


def _col(label: str) -> int:
    index = 0
    for ch in label:
        index = index * 26 + ord(ch) - ord("A") + 1
    return index - 1


def _rows(zf: zipfile.ZipFile, sheet: str, strings: list[str]):
    root = ET.fromstring(zf.read(sheet))
    for row in root.findall(f".//{NS}sheetData/{NS}row"):
        cell_map = {}
        for c in row.findall(f"{NS}c"):
            match = COL_RE.fullmatch(c.get("r", ""))
            if not match:
                continue
            kind = c.get("t")
            raw = c.find(f"{NS}v")
            if kind == "inlineStr":
                value = "".join(x.text or "" for x in c.iter(f"{NS}t"))
            elif raw is None:
                value = ""
            elif kind == "s":
                try:
                    value = strings[int(raw.text or "0")]
                except (ValueError, IndexError) as exc:
                    raise ImportErrorPlan("Índice de texto XLSX incorrecto") from exc
            else:
                value = raw.text or ""
            cell_map[_col(match.group(1))] = value.strip()
        if cell_map:
            yield cell_map


def _read_sheets(path: Path):
    if not path.is_file() or path.suffix.lower() != ".xlsx":
        raise ImportErrorPlan("Selecciona un fichero .xlsx descargado del Drive")
    if path.stat().st_size > 20_000_000:
        raise ImportErrorPlan("El Excel supera 20 MB; requiere revisión manual")
    try:
        with zipfile.ZipFile(path) as zf:
            files = zf.namelist()
            if len(files) > 3000 or sum(i.file_size for i in zf.infolist()) > 60_000_000:
                raise ImportErrorPlan("Archivo XLSX excesivamente grande")
            ss = []
            if "xl/sharedStrings.xml" in files:
                ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                ss = ["".join(t.text or "" for t in si.iter(f"{NS}t"))
                      for si in ss_root.findall(f"{NS}si")]
            sheets = sorted(
                n for n in files
                if re.fullmatch(r"xl/worksheets/sheet[0-9]+\.xml", n)
            )
            if not sheets:
                raise ImportErrorPlan("No hay hojas de cálculo XLSX legibles")
            for filename in sheets:
                yield filename, list(_rows(zf, filename, ss))
    except (zipfile.BadZipFile, ET.ParseError) as exc:
        raise ImportErrorPlan("XLSX inválido o XML malformado") from exc


def _num_int(value: str) -> int:
    try:
        f = float(value)
    except (ValueError, TypeError) as exc:
        raise ImportErrorPlan(f"Duración no numérica: {value!r}") from exc
    if not f.is_integer() or not 0 <= f <= 400:
        raise ImportErrorPlan(f"Duración fuera de rango: {value!r}")
    return int(f)


def _km(value: str) -> float | None:
    if not value or value in {"—", "-", "–"}:
        return None
    try:
        n = float(value.replace(",", "."))
    except (ValueError, TypeError):
        return None  # objetivos cualitativos no se convierten a kilómetros falsos
    return n if 0 < n < 100 else None


def import_workbook(path: Path, *, reference: dict | None = None) -> dict:
    base = copy.deepcopy(reference or planning._snapshot())
    windows = {w["id"]: w for w in base["weeks"]}
    found: dict[str, dict[str, dict]] = {k: {} for k in windows}
    count_header = 0
    for filename, rows in _read_sheets(path):
        header: dict[str, int] = {}
        for row in rows:
            names = {_norm(v): k for k, v in row.items()}
            if {"SEMANA", "DIA", "TIPO", "SESION", "MIN"}.issubset(names):
                header = names
                count_header += 1
                continue
            if not header:
                continue
            def field(name: str) -> str:
                return row.get(header.get(name, -1), "")
            week = _norm(field("SEMANA"))
            day = _norm(field("DIA"))
            if week not in found or day not in DAY_NAMES:
                continue
            typ = _norm(field("TIPO"))
            if typ not in {"Z2", "CALIDAD", "MLR", "LARGO", "DESCANSO", "TEST"}:
                raise ImportErrorPlan(f"{filename}: tipo desconocido {typ!r} en {week}/{day}")
            title = field("SESION")
            if not title:
                raise ImportErrorPlan(f"{filename}: sesión vacía {week}/{day}")
            stamp = date.fromisoformat(windows[week]["start"]).toordinal()
            iso = date.fromordinal(stamp + DAY_NAMES.index(day)).isoformat()
            detail = field("DETALLES")
            notes = field("NOTAS")
            duration = _num_int(field("MIN")) if typ != "DESCANSO" else 0
            if typ != "DESCANSO" and duration == 0:
                raise ImportErrorPlan(f"Duración 0 para entrenamiento {week}/{day}")
            shoe = field("CALZADO")
            fuel = field("FUELING")
            alert = field("ALERTA")
            strength = re.search(r"FUERZA(?: FULL BODY| MANTENIMIENTO| ACTIVACI[OÓ]N)?"
                                 r"(?: LIGERA)?\s+(\d+)\s*min", title, re.I)
            candidate = {
                "date": iso, "weekday": day.lower(),
                "type": typ, "title": title, "detail": detail, "notes": notes,
                "duration_min": duration, "km_estimate": _km(field("KM")),
                "shoe": shoe if shoe and shoe != "—" else None,
                "during_fuel": fuel if fuel and fuel != "—" else None,
                "alert": alert if alert and alert != "—" else None,
                "strength_min": int(strength.group(1)) if strength else None,
            }
            previous = found[week].get(iso)
            if previous is not None and previous != candidate:
                raise ImportErrorPlan(
                    f"Datos contradictorios para {week}/{day} en varias hojas; "
                    "no es seguro escoger automáticamente"
                )
            found[week][iso] = candidate
    if not count_header:
        raise ImportErrorPlan("No hay cabeceras SEMANA, DÍA, TIPO, SESIÓN, MIN")
    for label, w in windows.items():
        sessions = sorted(found[label].values(), key=lambda x: x["date"])
        if len(sessions) != 7:
            raise ImportErrorPlan(
                f"{label} tiene {len(sessions)}/7 días válidos; "
                "no se importan semanas parciales"
            )
        w["sessions"] = sessions
        w["run_minutes"] = sum(s["duration_min"] for s in sessions)
        km = [s["km_estimate"] for s in sessions if s["type"] != "DESCANSO"]
        w["run_km_approx"] = (round(sum(km), 1) if len(km) == 6 and
                              all(v is not None for v in km) else None)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    base["source_name"] = path.name[:160]
    base["source_version"] = f"Excel local revisado · sha256 {sha[:12]}"
    base["source_sha256"] = sha
    base["source_status"] = "LOCAL_XLSX_STRUCTURE_VERIFIED_NOT_REMOTE"
    base["imported_at"] = datetime.now(UTC).date().isoformat()
    # Enlace solo al fichero de referencia autorizado del proyecto;
    # no implica que los bytes locales sean idénticos a los remotos.
    planning.validate_snapshot(base)
    return base


def changes(old: dict, new: dict) -> list[dict]:
    original = {s["date"]: s for w in old["weeks"] for s in w["sessions"]}
    revised = {s["date"]: s for w in new["weeks"] for s in w["sessions"]}
    if set(original) != set(revised):
        raise ImportErrorPlan("Fechas modificadas; requiere revisión del plan maestro")
    diffs = []
    for date_ in sorted(original):
        fields = [name for name in FIELDS if original[date_].get(name) != revised[date_].get(name)]
        if fields:
            diffs.append({"date": date_, "fields": fields,
                          "old_title": original[date_]["title"],
                          "new_title": revised[date_]["title"]})
    return diffs


def save_local(destination: Path, data: dict) -> Path | None:
    """Escritura atómica y copia de seguridad de una versión local previa."""
    planning.validate_snapshot(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".ares-plan-",
                                   suffix=".tmp")
        temporary = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        backup = None
        if destination.is_file():
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            backup = destination.with_name(f"training_plan.backup-{stamp}.json")
            shutil.copy2(destination, backup)
        os.replace(temporary, destination)
        return backup
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
