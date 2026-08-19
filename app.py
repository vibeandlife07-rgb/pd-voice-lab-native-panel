from __future__ import annotations

import csv
import os
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import streamlit as st

APP_ROOT = Path(__file__).resolve().parent
LOCAL_RESPONSES = APP_ROOT / "responses.csv"
VOICE_LABELS = ("A", "B", "C", "D")
RATING_FIELDS = ("naturalness", "humanity", "listenability", "pronunciation", "rhythm_intonation", "synthetic")
SPREADSHEET_ID = "1uuQ4ueqVl0LOonfxU4cUr_d0pxYv5HTJDYV4YBy1fCY"
WORKSHEET_NAME = "responses"
AUDIO_BUNDLE_FILE_ID = "1oiedVe8Prt2Ti9j3deYxTF76N918lJOH"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
SURVEYCIRCLE_CODE = "6LPU-L7GS-Z5R8-N37Z"
SURVEYCIRCLE_ONE_CLICK = "https://www.surveycircle.com/6LPU-L7GS-Z5R8-N37Z/"
SERVICE_ACCOUNT_FIELDS = (
    "type", "project_id", "private_key_id", "private_key", "client_email", "client_id",
    "auth_uri", "token_uri", "auth_provider_x509_cert_url", "client_x509_cert_url",
)
CSV_COLUMNS = [
    "response_id", "timestamp", "native_spanish", "country_region",
    *[f"{voice}_{field}" for voice in VOICE_LABELS for field in RATING_FIELDS],
    "preferred_voice", "preferred_short", "preferred_mid", "preferred_long",
    "odd_phrase_or_pause", "comment", "source",
]


def cfg(section: str, key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(section, {}).get(key, default))
    except Exception:
        return default


def service_account_dict() -> dict[str, str]:
    return {field: cfg("gcp_service_account", field) for field in SERVICE_ACCOUNT_FIELDS}


def response_mode() -> str:
    return cfg("panel", "response_mode", os.environ.get("RESPONSE_MODE", "GOOGLE_SHEETS")).strip().upper()


def ensure_local_csv() -> None:
    if not LOCAL_RESPONSES.exists():
        with LOCAL_RESPONSES.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=CSV_COLUMNS).writeheader()


def write_local(row: dict[str, str | int]) -> None:
    ensure_local_csv()
    with LOCAL_RESPONSES.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=CSV_COLUMNS).writerow(row)


def backend_status() -> tuple[bool, str]:
    missing = [k for k, v in service_account_dict().items() if not v]
    if missing:
        return False, "Faltan las credenciales privadas del backend."
    if cfg("google_sheets", "spreadsheet_id") != SPREADSHEET_ID or cfg("google_sheets", "worksheet") != WORKSHEET_NAME:
        return False, "La hoja configurada no coincide con el panel."
    return True, "GOOGLE_SHEETS listo."


@st.cache_data(ttl=3600, show_spinner=False)
def load_audio() -> dict[str, bytes]:
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    info = service_account_dict()
    creds = service_account.Credentials.from_service_account_info(info, scopes=[DRIVE_SCOPE])
    session = AuthorizedSession(creds)
    response = session.get(f"https://www.googleapis.com/drive/v3/files/{AUDIO_BUNDLE_FILE_ID}?alt=media", timeout=90)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")
    result: dict[str, bytes] = {}
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        for label in VOICE_LABELS:
            name = f"VOICE-{label}.mp3"
            result[label] = archive.read(name)
    return result


def write_sheet(row: dict[str, str | int]) -> None:
    import gspread

    client = gspread.service_account_from_dict(service_account_dict())
    ws = client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
    header = ws.row_values(1)
    if not header:
        ws.append_row(CSV_COLUMNS, value_input_option="RAW")
    elif header != CSV_COLUMNS:
        raise RuntimeError("Incompatible worksheet header")
    ws.append_row([row[c] for c in CSV_COLUMNS], value_input_option="RAW")


def rating(voice: str, field: str, title: str, hint: str) -> int | None:
    return st.selectbox(title, [None, 1, 2, 3, 4, 5], format_func=lambda x: "Selecciona una puntuación" if x is None else str(x), help=hint, key=f"{voice}_{field}")


def choice(title: str, key: str) -> str | None:
    return st.selectbox(title, [None, *VOICE_LABELS], format_func=lambda x: "Selecciona una voz" if x is None else x, key=key)


def main() -> None:
    st.set_page_config(page_title="PD VOICE LAB — Prueba ciega", page_icon="🎧")
    st.title("PD VOICE LAB — Prueba ciega de voz")
    st.info("Escucha las cuatro voces con auriculares si es posible.\n\nNo intentes adivinar el proveedor, la velocidad ni cuál usamos actualmente.\n\nEvalúa únicamente cómo percibes cada voz en español.")

    mode = response_mode()
    ready, message = backend_status()
    if mode == "GOOGLE_SHEETS":
        st.caption(f"Backend: {message}") if ready else st.warning(message)
    elif mode == "LOCAL_CSV":
        ready = True
        st.caption("Backend: LOCAL_CSV")
    else:
        st.error("Configuración de almacenamiento no válida.")
        return

    try:
        audio = load_audio()
    except Exception:
        st.error("Los audios del panel no están disponibles en este momento.")
        return

    scores: dict[str, int | None] = {}
    with st.form("native_panel_form"):
        for voice in VOICE_LABELS:
            st.subheader(f"VOICE {voice}")
            st.audio(audio[voice], format="audio/mpeg")
            scores[f"{voice}_naturalness"] = rating(voice, "naturalness", "Naturalidad", "1 = muy artificial · 5 = muy natural")
            scores[f"{voice}_humanity"] = rating(voice, "humanity", "Sensación humana", "1 = claramente sintética · 5 = parece una persona real")
            scores[f"{voice}_listenability"] = rating(voice, "listenability", "Comodidad para escuchar durante 5–10 minutos", "1 = cansaría rápido · 5 = podría escucharla sin problema")
            scores[f"{voice}_pronunciation"] = rating(voice, "pronunciation", "Pronunciación natural", "1 = muy poco natural · 5 = muy natural")
            scores[f"{voice}_rhythm_intonation"] = rating(voice, "rhythm_intonation", "Ritmo e entonación", "1 = muy poco naturales · 5 = muy naturales")
            scores[f"{voice}_synthetic"] = rating(voice, "synthetic", "Presencia de efecto sintético", "1 = casi no se percibe · 5 = muy evidente")
            st.divider()

        preferred = choice("¿Qué voz elegirías en general para un canal de psicología práctica?", "preferred_voice")
        preferred_short = choice("¿Cuál elegirías para un video corto de 40–60 segundos?", "preferred_short")
        preferred_mid = choice("¿Cuál elegirías para un video de 5–7 minutos?", "preferred_mid")
        preferred_long = choice("¿Cuál elegirías para un video de 10–20 minutos?", "preferred_long")
        odd = st.text_area("¿Hay alguna palabra, frase, pausa o entonación que suene extraña? (opcional)")
        comment = st.text_area("Comentario adicional (opcional)")
        country = st.text_input("País o región")
        native = st.selectbox("¿Eres hablante nativo de español?", [None, "Sí", "No"], format_func=lambda x: "Selecciona una opción" if x is None else x)
        submitted = st.form_submit_button("Guardar evaluación", disabled=not ready)

    if not submitted:
        return
    missing = any(v is None for v in scores.values()) or any(x not in VOICE_LABELS for x in (preferred, preferred_short, preferred_mid, preferred_long)) or native not in ("Sí", "No")
    if missing:
        st.error("Completa todas las puntuaciones, las cuatro selecciones y la pregunta sobre español nativo.")
        return

    row: dict[str, str | int] = {
        "response_id": str(uuid.uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
        "native_spanish": native, "country_region": country.strip(),
        "preferred_voice": preferred, "preferred_short": preferred_short,
        "preferred_mid": preferred_mid, "preferred_long": preferred_long,
        "odd_phrase_or_pause": odd.strip(), "comment": comment.strip(), "source": mode,
    }
    for voice in VOICE_LABELS:
        for field in RATING_FIELDS:
            row[f"{voice}_{field}"] = int(scores[f"{voice}_{field}"])
    try:
        write_sheet(row) if mode == "GOOGLE_SHEETS" else write_local(row)
    except Exception:
        st.error("No se pudo guardar la evaluación. Inténtalo más tarde.")
        return

    st.success("Gracias. Tu evaluación se ha guardado correctamente.")
    st.markdown("### SurveyCircle")
    st.write("Tu participación ya está guardada. Ahora puedes acreditar tu participación en SurveyCircle.")
    st.link_button("Activar mi Survey Code en SurveyCircle", SURVEYCIRCLE_ONE_CLICK)
    st.caption(f"Si lo necesitas, el código manual es: {SURVEYCIRCLE_CODE}")


if __name__ == "__main__":
    main()
