"""Control de versiones XLSX: leer sin macros, auditar y recuperar versiones."""
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from ares.app import planning, plan_workbook


N = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
HEAD = ["SEMANA","FECHAS","DÍA","TIPO","SESIÓN","DETALLES","NOTAS",
        "MIN","MIN RM","MIN UMB","KM","CALZADO","FUELING","ALERTA"]


def _xlsx(path: Path, *, change=None, exclude=None, add_conflict=False):
    root = ET.Element(f"{{{N}}}worksheet")
    data = ET.SubElement(root, f"{{{N}}}sheetData")

    def add(row_n, values):
        row = ET.SubElement(data, f"{{{N}}}row", {"r":str(row_n)})
        for i,v in enumerate(values):
            col = chr(ord("A")+i)
            cell = ET.SubElement(row,f"{{{N}}}c",{"r":f"{col}{row_n}","t":"inlineStr"})
            text = ET.SubElement(ET.SubElement(cell,f"{{{N}}}is"),f"{{{N}}}t")
            text.text = "" if v is None else str(v)

    add(1,HEAD)
    baseline = planning._snapshot()
    order = ["LUN","MAR","MIE","JUE","VIE","SAB","DOM"]
    row_n = 2
    for w in baseline["weeks"]:
        for i,s in enumerate(w["sessions"]):
            if exclude == s["date"]:
                continue
            title = change if s["date"]=="2026-10-12" and change else s["title"]
            values=[
                w["id"],"12-18 Octubre",order[i],s["type"],title,
                s["detail"],s["notes"],s["duration_min"],"","",
                s["km_estimate"] if s["km_estimate"] is not None else "",
                s["shoe"] or "",s["during_fuel"] or "",s["alert"] or "",
            ]
            add(row_n,values)
            row_n+=1
    with ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml",ET.tostring(root,encoding="utf-8"))
        if add_conflict:
            z.writestr("xl/worksheets/sheet2.xml",ET.tostring(root,encoding="utf-8"))


def test_un_excel_bien_formado_recupera_63_dias_sin_cambiar_bloques(tmp_path):
    source=tmp_path/"maestro.xlsx"
    _xlsx(source)
    imported=plan_workbook.import_workbook(source)
    assert len(imported["weeks"])==9
    assert sum(len(w["sessions"]) for w in imported["weeks"])==63
    assert plan_workbook.changes(planning._snapshot(),imported)==[]
    assert len(imported["source_sha256"])==64


def test_diff_es_dia_y_campos_no_reemplazo_silencioso(tmp_path):
    source=tmp_path/"maestro-nuevo.xlsx"
    _xlsx(source,change="Z2 60 min + 4 strides revisado")
    imported=plan_workbook.import_workbook(source)
    changed=plan_workbook.changes(planning._snapshot(),imported)
    assert len(changed)==1
    assert changed[0]["date"]=="2026-10-12"
    assert changed[0]["fields"]==["title"]
    assert changed[0]["old_title"]!=changed[0]["new_title"]


def test_no_reemplaza_plan_si_falta_una_sesion(tmp_path):
    source=tmp_path/"incompleto.xlsx"
    _xlsx(source,exclude="2026-10-14")
    with pytest.raises(plan_workbook.ImportErrorPlan,match="6/7"):
        plan_workbook.import_workbook(source)


def test_override_ato_mico_con_backup_y_lectura_actualizada(tmp_path):
    source=tmp_path/"maestro-v10.xlsx"
    _xlsx(source,change="Z2 revisado autorizado")
    imported=plan_workbook.import_workbook(source)
    destination=tmp_path/"training_plan.json"
    assert plan_workbook.save_local(destination,imported) is None
    current=planning.plan(week="S32",source_file=destination)
    assert current["days"][0]["title"]=="Z2 revisado autorizado"
    assert current["sync"]=="SNAPSHOT_LOCAL_VERIFIED_NO_LIVE_DRIVE"
    # Segunda actualización: se crea una copia legible de la primera.
    source2=tmp_path/"maestro-v11.xlsx"
    _xlsx(source2,change="Z2 segunda revisión")
    next_plan=plan_workbook.import_workbook(source2)
    backup=plan_workbook.save_local(destination,next_plan)
    assert backup is not None and backup.is_file()
    assert planning._snapshot(backup)["weeks"][0]["sessions"][0]["title"]=="Z2 revisado autorizado"
    assert planning._snapshot(destination)["weeks"][0]["sessions"][0]["title"]=="Z2 segunda revisión"


def test_no_acepta_zip_que_no_es_excel_ni_formato_de_otro_plan(tmp_path):
    bad=tmp_path/"no.xlsx"
    bad.write_text("Esto no es un Excel",encoding="utf-8")
    with pytest.raises(plan_workbook.ImportErrorPlan):
        plan_workbook.import_workbook(bad)


def test_no_acepta_datos_contradictorios_entre_hojas(tmp_path):
    # Emplea dos hojas generadas por separado y modifica la segunda.
    first=tmp_path/"base.xlsx"
    second=tmp_path/"otro.xlsx"
    target=tmp_path/"duplicado.xlsx"
    _xlsx(first)
    _xlsx(second,change="Sesión alterada")
    with ZipFile(first) as a, ZipFile(second) as b, ZipFile(target,"w") as out:
        out.writestr("xl/worksheets/sheet1.xml",a.read("xl/worksheets/sheet1.xml"))
        out.writestr("xl/worksheets/sheet2.xml",b.read("xl/worksheets/sheet1.xml"))
    with pytest.raises(plan_workbook.ImportErrorPlan,match="contradictorios"):
        plan_workbook.import_workbook(target)
