#!/usr/bin/env python3
"""
Sincroniza data.json desde la hoja de Google Sheets de BioMar (publicada
en la web) para el dashboard de GitHub Pages.

Fuente: pestana "DATA" publicada en la web (Archivo > Compartir >
Publicar en la web, con "Republicar automaticamente" activado).

IMPORTANTE: la columna "N" (columna 1) puede venir vacia en filas
reales recientes -- NUNCA usar esa columna para detectar filas con
datos. Una fila es real si la columna 2 (FECHA DE INICIO) tiene forma
de fecha "AAAA/MM/DD HH:MM:SS", sin importar si la columna 1 esta vacia.
"""
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta

SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSnoZyZzgWVCu29zqNVHPPOMLGTAUZAHPBq2i2dImpP7HdcsPvqF6ic1a4kLCPx4A/pub?gid=1584714381&single=true&output=csv"

ANEXO_A = {
    "PFK9655": "ROBERTO ACOSTA", "GTR4789": "MIGUEL AGUILAR", "GTR5575": "JUAN KARLO GONZALEZ",
    "GTQ1645": "VICTOR SANCHEZ", "GTN2014": "BYRON SANCHEZ", "PDX8596": "JOSE EDUARDO JARAMILLO",
    "GTM2390": "ADRIAN VERA", "GTM2394": "ALEXANDRA VILELA", "GTM2391": "SARA CARRERA",
    "GTM2392": "MARIA PIA ARGUELLO", "GTL5525": "CARLOS ARAMBULU", "GTL5524": "JULIAN ZEDENO",
    "GTL5523": "BRYAN JIMENEZ", "GTL1967": "BYRON VELASQUEZ", "GTL1966": "MANUEL CALDERON",
    "GTL1965": "RAUL RAMIREZ", "GTL1964": "MARIA JOSE ASTUDILLO", "PDV6675": "VIVIANA AGUILAR",
    "PDV6679": "LUZ DELGADO", "PDV2431": "JHONNY VALENZUELA", "PDV2468": "MARCO DELGADO",
    "PCZ1887": "VERONICA ALCIVAR", "PCZ1889": "RICHARD ESCOBEDO", "ABM2796": "ANDRES RIVADULLA",
    "PFP3174": "GIANI YEPEZ", "PFP3171": "LAURENCE MASSAUT", "PFP3178": "EDUARDO CORONA",
    "PFS1355": "SOCRATES ALMEIDA",
}

DATE_RE = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}")


def parse_num(s):
    if not s or not s.strip():
        return 0.0
    return float(s.strip().replace(",", "."))


def fetch_rows():
    req = urllib.request.Request(SHEET_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    lines = raw.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("N,"):
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError("Header row not found in sheet export")
    data_lines = [l for l in lines[header_idx + 1:] if DATE_RE.match(l.split(",", 1)[1] if "," in l else "")]
    # re-parse properly with csv module for quoted fields
    reader = csv.reader(io.StringIO("\n".join(data_lines)))
    rows = []
    for cols in reader:
        if len(cols) < 18:
            continue
        if not DATE_RE.match(cols[1].strip()):
            continue
        rows.append(cols)
    return rows


def build_data():
    rows = fetch_rows()
    units = {}
    for cols in rows:
        placa = cols[7].strip()
        if not placa:
            continue
        conductor = cols[8].strip()
        day = cols[1].strip()[:10].replace("/", "-")
        km = parse_num(cols[16])
        odo_ini = parse_num(cols[14])
        odo_fin = parse_num(cols[15])
        tipo = cols[12].strip()
        fecha_ini = cols[1].strip()
        fecha_fin = cols[4].strip()
        ciudad = cols[10].strip()
        ubic = cols[11].strip()

        u = units.setdefault(placa, {"conductor": "", "days": {}})
        if conductor and conductor != "SIN REGISTRO DE NOMBRE":
            u["conductor"] = conductor
        elif not u["conductor"]:
            u["conductor"] = conductor

        d = u["days"].setdefault(day, {
            "km": 0.0, "movimiento": False, "hora_inicio": fecha_ini, "hora_fin": fecha_fin,
            "odo_min": odo_ini, "odo_max": odo_fin, "ciudad_inicio": ciudad, "ciudad_fin": ciudad,
            "ubic_inicio": ubic, "ubic_fin": ubic,
        })
        d["km"] = round(d["km"] + km, 1)
        if tipo == "Viaje" and km > 0:
            d["movimiento"] = True
        if odo_ini < d["odo_min"]:
            d["odo_min"] = odo_ini
            d["hora_inicio"] = fecha_ini
            d["ciudad_inicio"] = ciudad
            d["ubic_inicio"] = ubic
        if odo_fin > d["odo_max"]:
            d["odo_max"] = odo_fin
            d["hora_fin"] = fecha_fin
            d["ciudad_fin"] = ciudad
            d["ubic_fin"] = ubic

    if not units:
        raise RuntimeError("No units parsed from sheet - refusing to overwrite data.json")

    all_dates = sorted({d for u in units.values() for d in u["days"]})
    min_date = datetime.strptime(all_dates[0], "%Y-%m-%d").date()
    max_date = datetime.strptime(all_dates[-1], "%Y-%m-%d").date()
    fechas = []
    cur = min_date
    while cur <= max_date:
        fechas.append(cur.isoformat())
        cur += timedelta(days=1)

    no_monitoreadas = [
        {"placa": p, "conductor": c} for p, c in ANEXO_A.items() if p not in units
    ]

    unidades_out = []
    km_total_flota = 0.0
    for placa in sorted(units.keys()):
        u = units[placa]
        dias_out = []
        last_odo = None
        last_ciudad = ""
        km_total_unidad = 0.0
        dias_con_mov = 0
        odometro_inicial = None
        for f in fechas:
            if f in u["days"]:
                d = u["days"][f]
                if odometro_inicial is None:
                    odometro_inicial = d["odo_min"]
                dias_out.append({
                    "fecha": f, "km": d["km"], "movimiento": d["movimiento"],
                    "hora_inicio": d["hora_inicio"] if d["movimiento"] else None,
                    "hora_fin": d["hora_fin"] if d["movimiento"] else None,
                    "km_inicial": d["odo_min"], "km_final": d["odo_max"],
                    "ciudad_inicial": d["ciudad_inicio"], "ciudad_final": d["ciudad_fin"],
                    "ubicacion_inicial": d["ubic_inicio"], "ubicacion_final": d["ubic_fin"],
                })
                last_odo = d["odo_max"]
                last_ciudad = d["ciudad_fin"]
                km_total_unidad += d["km"]
                if d["movimiento"]:
                    dias_con_mov += 1
            else:
                dias_out.append({
                    "fecha": f, "km": 0.0, "movimiento": False, "hora_inicio": None, "hora_fin": None,
                    "km_inicial": last_odo, "km_final": last_odo,
                    "ciudad_inicial": last_ciudad, "ciudad_final": last_ciudad,
                    "ubicacion_inicial": None, "ubicacion_final": None,
                })
        km_total_unidad = round(km_total_unidad, 1)
        km_total_flota += km_total_unidad
        unidades_out.append({
            "placa": placa, "conductor": u["conductor"], "km_total_periodo": km_total_unidad,
            "dias_con_movimiento": dias_con_mov, "dias_registrados": len(fechas),
            "promedio_diario": round(km_total_unidad / dias_con_mov, 1) if dias_con_mov > 0 else 0.0,
            "odometro_inicial": odometro_inicial, "odometro_actual": last_odo, "dias": dias_out,
        })

    meta = {
        "cliente": "BIOMAR (Alimentsa S.A.)", "periodo_inicio": fechas[0], "periodo_fin": fechas[-1],
        "fechas": fechas, "total_unidades": len(unidades_out), "km_total_flota": round(km_total_flota, 1),
        "unidades_no_monitoreadas": no_monitoreadas, "generado": date.today().isoformat(),
        "fuente": "Matriz GPS - Telearseg - Biomar (Google Sheets, publicado en la web)",
    }
    return {"meta": meta, "unidades": unidades_out}


def main():
    data = build_data()
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"OK. Unidades: {len(data['unidades'])}. Periodo: {data['meta']['periodo_inicio']} a "
          f"{data['meta']['periodo_fin']}. Km flota: {data['meta']['km_total_flota']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
