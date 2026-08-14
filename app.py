"""Blind native-panel app suitable for local use or Streamlit Community Cloud."""

from __future__ import annotations

import csv
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st


APP_ROOT = Path(__file__).resolve().parent
ASSETS = APP_ROOT / "assets"
LOCAL_RESPONSES = APP_ROOT / "responses.csv"
VOICE_LABELS = ("A", "B", "C")
RATING_FIELDS = ("naturalness", "humanity", "listenability", "pronunciation", "rhythm_intonation", "synthetic")
SPREADSHEET_ID = "1uuQ4ueqVl0LOonfxU4cUr_d0pxYv5HTJDYV4YBy1fCY"
WORKSHEET_NAME = "responses"
SERVICE_ACCOUNT_FIELDS = (
    "type", "project_id", "private_key_id", "private_key", "client_email", "client_id",
    "auth_uri", "token_uri", "auth_provider_x509_cert_url", "client_x509_cert_url",
)
CSV_COLUMNS = [
    "response_id", "timestamp", "native_spanish", "country_region",
    *[f"{voice}_{field}" for voice in VOICE_LABELS for field in RATING_FIELDS],
    "preferred_voice", "odd_phrase_or_pause", "comment", "source",
]


def config_value(section: str, key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(section, {}).get(key, default))
    except Exception:
        return default


def response_mode() -> str:
    # Safe default: a public deployment cannot silently fall back to local storage.
    value = config_value("panel", "response_mode", os.environ.get("RESPONSE_MODE", "GOOGLE_SHEETS"))
    return value.strip().upper()


def ensure_local_csv() -> None:
    if not LOCAL_RESPONSES.exists():
        with LOCAL_RESPONSES.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=CSV_COLUMNS).writeheader()


def write_local(row: dict[str, str | int]) -> None:
    ensure_local_csv()
    with LOCAL_RESPONSES.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=CSV_COLUMNS).writerow(row)


def google_sheets_status() -> tuple[bool, str]:
    configured_id = config_value("google_sheets", "spreadsheet_id")
    configured_sheet = config_value("google_sheets", "worksheet")
    missing = [field for field in SERVICE_ACCOUNT_FIELDS if not config_value("gcp_service_account", field)]
    if missing:
        return False, "Faltan las credenciales privadas del backend de respuestas."
    if configured_id != SPREADSHEET_ID or configured_sheet != WORKSHEET_NAME:
        return False, "La hoja de respuestas configurada no coincide con el panel aprobado."
    return True, "Google Sheets está configurado para guardar respuestas."


def write_google_sheet(row: dict[str, str | int]) -> None:
    """Append using Streamlit secrets only; no credential is stored in this repository."""
    import gspread

    credentials = {field: config_value("gcp_service_account", field) for field in SERVICE_ACCOUNT_FIELDS}
    client = gspread.service_account_from_dict(credentials)
    worksheet = client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
    header = worksheet.row_values(1)
    if not header:
        worksheet.append_row(CSV_COLUMNS, value_input_option="RAW")
    elif header != CSV_COLUMNS:
        raise RuntimeError("The configured worksheet has an incompatible header.")
    worksheet.append_row([row[column] for column in CSV_COLUMNS], value_input_option="RAW")


def build_row(scores: dict[str, int | None], preferred: str, odd_phrase_or_pause: str, comment: str, country: str, native: str, source: str) -> dict[str, str | int]:
    row: dict[str, str | int] = {
        "response_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "native_spanish": native,
        "country_region": country.strip(),
        "preferred_voice": preferred,
        "odd_phrase_or_pause": odd_phrase_or_pause.strip(),
        "comment": comment.strip(),
        "source": source,
    }
    for voice in VOICE_LABELS:
        for field in RATING_FIELDS:
            row[f"{voice}_{field}"] = int(scores[f"{voice}_{field}"])
    return row


def rating(voice: str, field: str, title: str, hint: str) -> int | None:
    return st.selectbox(
        title,
        options=[None, 1, 2, 3, 4, 5],
        format_func=lambda value: "Selecciona una puntuación" if value is None else str(value),
        help=hint,
        key=f"{voice}_{field}",
    )


def main() -> None:
    st.set_page_config(page_title="PD VOICE LAB — Prueba de voz", page_icon="🎧")
    st.title("PD VOICE LAB — Prueba de voz")
    st.info("Escucha las tres voces con auriculares si es posible.\n\nNo intentes adivinar cuál es la configuración actual.\n\nEvalúa solo cómo percibes la voz.")

    mode = response_mode()
    if mode not in ("LOCAL_CSV", "GOOGLE_SHEETS"):
        st.error("La configuración de almacenamiento de respuestas no es válida.")
        return
    google_ready, google_message = google_sheets_status()
    backend_ready = mode == "LOCAL_CSV" or google_ready
    if mode == "LOCAL_CSV":
        st.caption("Estado del backend: LOCAL_CSV (solo para pruebas locales; no usar para publicación pública).")
    elif google_ready:
        st.caption("Estado del backend: GOOGLE_SHEETS — listo para guardar respuestas persistentes.")
    else:
        st.warning(f"Estado del backend: GOOGLE_SHEETS no disponible. {google_message} La evaluación no se enviará.")

    scores: dict[str, int | None] = {}
    with st.form("native_panel_form"):
        for voice in VOICE_LABELS:
            path = ASSETS / f"VOICE-{voice}.mp3"
            if not path.is_file():
                st.error(f"No se encontró el audio {voice}.")
                return
            st.subheader(f"VOICE {voice}")
            st.audio(path.read_bytes(), format="audio/mpeg")
            scores[f"{voice}_naturalness"] = rating(voice, "naturalness", "Naturalidad", "1 = muy artificial · 5 = muy natural")
            scores[f"{voice}_humanity"] = rating(voice, "humanity", "Sensación humana", "1 = claramente sintética · 5 = parece una persona real")
            scores[f"{voice}_listenability"] = rating(voice, "listenability", "Comodidad para escuchar durante 5–10 minutos", "1 = cansaría rápido · 5 = podría escucharla sin problema")
            scores[f"{voice}_pronunciation"] = rating(voice, "pronunciation", "Pronunciación natural", "1 = muy poco natural · 5 = muy natural")
            scores[f"{voice}_rhythm_intonation"] = rating(voice, "rhythm_intonation", "Ritmo e entonación", "1 = muy poco naturales · 5 = muy naturales")
            scores[f"{voice}_synthetic"] = rating(voice, "synthetic", "Presencia de efecto sintético", "1 = casi no se percibe · 5 = muy evidente")
            st.divider()

        preferred = st.selectbox("¿Qué voz elegirías para un canal de psicología práctica?", [None, "A", "B", "C"], format_func=lambda value: "Selecciona una voz" if value is None else value)
        odd_phrase_or_pause = st.text_area("¿Hay alguna palabra, frase, pausa o entonación que suene extraña? (opcional)")
        comment = st.text_area("Comentario adicional (opcional)")
        country = st.text_input("País o región")
        native = st.selectbox("¿Eres hablante nativo de español?", [None, "Sí", "No"], format_func=lambda value: "Selecciona una opción" if value is None else value)
        submitted = st.form_submit_button("Guardar evaluación", disabled=not backend_ready)

    if submitted:
        required_missing = any(value is None for value in scores.values()) or preferred not in VOICE_LABELS or native not in ("Sí", "No")
        if required_missing:
            st.error("Completa todas las puntuaciones, la voz elegida y la pregunta sobre español nativo antes de guardar.")
            return
        row = build_row(scores, preferred, odd_phrase_or_pause, comment, country, native, mode)
        try:
            if mode == "GOOGLE_SHEETS":
                write_google_sheet(row)
            else:
                write_local(row)
        except Exception:
            st.error("No se pudo guardar la evaluación. Inténtalo más tarde.")
            return
        st.success("Gracias. Tu evaluación se ha guardado.")


if __name__ == "__main__":
    main()
