from __future__ import annotations

import csv
import os
import random
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import streamlit as st

APP_ROOT = Path(__file__).resolve().parent
LOCAL_RESPONSES = APP_ROOT / "responses.csv"
VOICE_LABELS = ("A", "B", "C", "D")
RATING_FIELDS = (
    "naturalness",
    "humanity",
    "listenability",
    "pronunciation",
    "rhythm_intonation",
    "synthetic",
)
SPREADSHEET_ID = "1uuQ4ueqVl0LOonfxU4cUr_d0pxYv5HTJDYV4YBy1fCY"
WORKSHEET_NAME = "responses"
CONFIG_WORKSHEET_NAME = "config"
AUDIO_BUNDLE_FILE_ID = "1oiedVe8Prt2Ti9j3deYxTF76N918lJOH"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
SERVICE_ACCOUNT_FIELDS = (
    "type",
    "project_id",
    "private_key_id",
    "private_key",
    "client_email",
    "client_id",
    "auth_uri",
    "token_uri",
    "auth_provider_x509_cert_url",
    "client_x509_cert_url",
)
CSV_COLUMNS = [
    "response_id",
    "timestamp",
    "native_spanish",
    "country_region",
    *[f"{voice}_{field}" for voice in VOICE_LABELS for field in RATING_FIELDS],
    "preferred_voice",
    "preferred_short",
    "preferred_mid",
    "preferred_long",
    "odd_phrase_or_pause",
    "comment",
    "source",
]


def cfg(section: str, key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(section, {}).get(key, default))
    except Exception:
        return default


def service_account_dict() -> dict[str, str]:
    return {field: cfg("gcp_service_account", field) for field in SERVICE_ACCOUNT_FIELDS}


def response_mode() -> str:
    return cfg(
        "panel",
        "response_mode",
        os.environ.get("RESPONSE_MODE", "GOOGLE_SHEETS"),
    ).strip().upper()


def ensure_local_csv() -> None:
    if not LOCAL_RESPONSES.exists():
        with LOCAL_RESPONSES.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=CSV_COLUMNS).writeheader()


def write_local(row: dict[str, str | int]) -> None:
    ensure_local_csv()
    with LOCAL_RESPONSES.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=CSV_COLUMNS).writerow(row)


def backend_status() -> tuple[bool, str]:
    if response_mode() == "LOCAL_CSV":
        return True, "LOCAL_CSV"

    if response_mode() != "GOOGLE_SHEETS":
        return False, "storage_mode"

    missing = [key for key, value in service_account_dict().items() if not value]
    if missing:
        return False, "credentials"

    if cfg("google_sheets", "spreadsheet_id") != SPREADSHEET_ID:
        return False, "spreadsheet"

    if cfg("google_sheets", "worksheet") != WORKSHEET_NAME:
        return False, "worksheet"

    return True, "GOOGLE_SHEETS"


@st.cache_data(ttl=3600, show_spinner=False)
def load_audio() -> dict[str, bytes]:
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_info(
        service_account_dict(), scopes=[DRIVE_SCOPE]
    )
    session = AuthorizedSession(credentials)
    response = session.get(
        f"https://www.googleapis.com/drive/v3/files/{AUDIO_BUNDLE_FILE_ID}?alt=media",
        timeout=90,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Audio bundle HTTP {response.status_code}")

    result: dict[str, bytes] = {}
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        expected = {f"VOICE-{label}.mp3" for label in VOICE_LABELS}
        if not expected.issubset(names):
            raise RuntimeError("Audio bundle is incomplete")

        for label in VOICE_LABELS:
            payload = archive.read(f"VOICE-{label}.mp3")
            if not payload:
                raise RuntimeError(f"VOICE-{label} is empty")
            result[label] = payload

    return result


def sheets_client():
    import gspread

    return gspread.service_account_from_dict(service_account_dict())


def write_sheet(row: dict[str, str | int]) -> None:
    client = sheets_client()
    worksheet = client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
    header = worksheet.row_values(1)

    if not header:
        worksheet.append_row(CSV_COLUMNS, value_input_option="RAW")
    elif header != CSV_COLUMNS:
        raise RuntimeError("Incompatible worksheet header")

    worksheet.append_row([row[column] for column in CSV_COLUMNS], value_input_option="RAW")


def load_completion_data() -> tuple[str, str]:
    """Read SurveyCircle redemption data only after a successful submission."""
    if response_mode() != "GOOGLE_SHEETS":
        return "", ""

    client = sheets_client()
    worksheet = client.open_by_key(SPREADSHEET_ID).worksheet(CONFIG_WORKSHEET_NAME)
    rows = worksheet.get("A1:B10")
    config: dict[str, str] = {}
    for row in rows:
        if len(row) >= 2 and row[0]:
            config[str(row[0]).strip()] = str(row[1]).strip()

    code = config.get("surveycircle_code", "")
    one_click = config.get("surveycircle_one_click", "")
    return code, one_click


def rating(voice: str, field: str, title: str, hint: str) -> int | None:
    return st.selectbox(
        title,
        [None, 1, 2, 3, 4, 5],
        format_func=lambda value: "Selecciona una puntuación" if value is None else str(value),
        help=hint,
        key=f"{voice}_{field}",
    )


def choice(title: str, key: str) -> str | None:
    return st.selectbox(
        title,
        [None, *VOICE_LABELS],
        format_func=lambda value: "Selecciona una voz" if value is None else value,
        key=key,
    )


def show_completion() -> None:
    st.success("Gracias. Tu evaluación se ha guardado correctamente.")

    code = ""
    one_click = ""
    try:
        code, one_click = load_completion_data()
    except Exception:
        pass

    if one_click:
        st.markdown("### SurveyCircle")
        st.write(
            "Tu participación ya está guardada. Ahora puedes acreditar tu participación en SurveyCircle."
        )
        st.link_button("Activar mi Survey Code en SurveyCircle", one_click)
        if code:
            st.caption(f"Si lo necesitas, el código manual es: {code}")
    else:
        st.info(
            "Tu evaluación está guardada. Si participas a través de SurveyCircle y no ves el enlace de acreditación, vuelve a la página del estudio."
        )


def main() -> None:
    st.set_page_config(page_title="PD VOICE LAB — Prueba ciega", page_icon="🎧")
    st.title("PD VOICE LAB — Prueba ciega de voz")

    if st.session_state.get("submission_done"):
        show_completion()
        return

    st.info(
        "Escucha las cuatro voces con auriculares si es posible.\n\n"
        "No intentes adivinar el proveedor, la velocidad ni cuál usamos actualmente.\n\n"
        "Evalúa únicamente cómo percibes cada voz en español."
    )

    ready, _ = backend_status()
    if not ready:
        st.error("El panel no está disponible temporalmente. Inténtalo más tarde.")
        return

    native_gate = st.radio(
        "Antes de empezar: ¿eres hablante nativo de español?",
        ["Sí", "No"],
        index=None,
        horizontal=True,
        key="native_gate",
    )

    if native_gate is None:
        st.info("Selecciona una opción para continuar.")
        return

    if native_gate == "No":
        st.warning(
            "Gracias por tu interés. Para esta prueba necesitamos hablantes nativos de español."
        )
        return

    country = st.text_input("País o región", key="country_region")

    try:
        audio = load_audio()
    except Exception:
        st.error("Los audios del panel no están disponibles en este momento.")
        return

    if "voice_order" not in st.session_state:
        st.session_state.voice_order = random.sample(list(VOICE_LABELS), k=len(VOICE_LABELS))
    voice_order = list(st.session_state.voice_order)

    scores: dict[str, int | None] = {}
    with st.form("native_panel_form"):
        for voice in voice_order:
            st.subheader(f"VOICE {voice}")
            st.audio(audio[voice], format="audio/mpeg")
            scores[f"{voice}_naturalness"] = rating(
                voice,
                "naturalness",
                "Naturalidad",
                "1 = muy artificial · 5 = muy natural",
            )
            scores[f"{voice}_humanity"] = rating(
                voice,
                "humanity",
                "Sensación humana",
                "1 = claramente sintética · 5 = parece una persona real",
            )
            scores[f"{voice}_listenability"] = rating(
                voice,
                "listenability",
                "Comodidad para escuchar durante 5–10 minutos",
                "1 = cansaría rápido · 5 = podría escucharla sin problema",
            )
            scores[f"{voice}_pronunciation"] = rating(
                voice,
                "pronunciation",
                "Pronunciación natural",
                "1 = muy poco natural · 5 = muy natural",
            )
            scores[f"{voice}_rhythm_intonation"] = rating(
                voice,
                "rhythm_intonation",
                "Ritmo e entonación",
                "1 = muy poco naturales · 5 = muy naturales",
            )
            scores[f"{voice}_synthetic"] = rating(
                voice,
                "synthetic",
                "Presencia de efecto sintético",
                "1 = casi no se percibe · 5 = muy evidente",
            )
            st.divider()

        listened_all = st.checkbox(
            "Confirmo que he escuchado las cuatro voces antes de elegir.",
            key="listened_all",
        )
        preferred = choice(
            "¿Qué voz elegirías en general para un canal de psicología práctica?",
            "preferred_voice",
        )
        preferred_short = choice(
            "¿Cuál elegirías para un video corto de 40–60 segundos?",
            "preferred_short",
        )
        preferred_mid = choice(
            "¿Cuál elegirías para un video de 5–7 minutos?",
            "preferred_mid",
        )
        preferred_long = choice(
            "¿Cuál elegirías para un video de 10–20 minutos?",
            "preferred_long",
        )
        odd = st.text_area(
            "¿Hay alguna palabra, frase, pausa o entonación que suene extraña? (opcional)"
        )
        comment = st.text_area("Comentario adicional (opcional)")
        submitted = st.form_submit_button("Guardar evaluación")

    if not submitted:
        return

    missing_scores = any(value is None for value in scores.values())
    missing_choices = any(
        value not in VOICE_LABELS
        for value in (preferred, preferred_short, preferred_mid, preferred_long)
    )

    if missing_scores or missing_choices or not listened_all:
        st.error(
            "Completa todas las puntuaciones, las cuatro selecciones y confirma que has escuchado las cuatro voces."
        )
        return

    if not country.strip():
        st.error("Indica tu país o región.")
        return

    row: dict[str, str | int] = {
        "response_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "native_spanish": "Sí",
        "country_region": country.strip(),
        "preferred_voice": preferred,
        "preferred_short": preferred_short,
        "preferred_mid": preferred_mid,
        "preferred_long": preferred_long,
        "odd_phrase_or_pause": odd.strip(),
        "comment": comment.strip(),
        "source": response_mode(),
    }

    for voice in VOICE_LABELS:
        for field in RATING_FIELDS:
            row[f"{voice}_{field}"] = int(scores[f"{voice}_{field}"])

    if st.session_state.get("submission_in_progress"):
        return

    st.session_state.submission_in_progress = True
    try:
        if response_mode() == "GOOGLE_SHEETS":
            write_sheet(row)
        else:
            write_local(row)
    except Exception:
        st.session_state.submission_in_progress = False
        st.error("No se pudo guardar la evaluación. Inténtalo más tarde.")
        return

    st.session_state.submission_in_progress = False
    st.session_state.submission_done = True
    st.rerun()


if __name__ == "__main__":
    main()
